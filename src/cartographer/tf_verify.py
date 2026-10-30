"""Stage 3: check a curated diagram against facts.json and the repo; drop what cannot be proven."""

import argparse
import json
import sys
from pathlib import Path

from cartographer.secret_patterns import contains_secret
from cartographer.tf_hint_check import unaccounted
from cartographer.verify_shared import (
    SECRET_REASON,
    check_assumptions,
    claim_id,
    code_hit,
    fix_groups,
    isolated_ids,
    needs_attention,
    render_report,
    shape_warnings,
)

HINT_KINDS = ("iam", "trigger", "route")


def _fact_hit(fact: dict | None, fact_id: str, src_tf: set[str], dst_tf: set[str]) -> str | None:
    if fact is None:
        return f"unknown fact {fact_id}"
    ends = {fact["src"], fact["dst"]}
    if src_tf and dst_tf:
        ok = (fact["src"] in src_tf and fact["dst"] in dst_tf) or (fact["src"] in dst_tf and fact["dst"] in src_tf)
    else:
        ok = bool((src_tf | dst_tf) & ends)
    return None if ok else f"fact {fact_id} ({fact['src']} -> {fact['dst']}) does not join the edge nodes"


def _check_evidence(
    evidence: list[dict], facts_by_id: dict, repo_root: Path, src_tf: set[str], dst_tf: set[str]
) -> tuple[list[dict], list[str]]:
    good, why = [], []
    for ev in evidence:
        if "fact" in ev:
            reason = _fact_hit(facts_by_id.get(ev["fact"]), ev["fact"], src_tf, dst_tf)
        elif "stated" in ev:
            reason = "stated evidence is for described diagrams"
        else:
            reason = code_hit(repo_root, ev)
        if reason is None:
            good.append(ev)
        else:
            why.append(reason)
    return good, why


def _unshown(
    facts: dict, nodes: list[dict], covered: set[frozenset[str]], kinds: tuple[str, ...] | None = HINT_KINDS
) -> list[str]:
    owner = {a: n["id"] for n in nodes for a in n["tf"]}
    seen: dict[tuple[str, str, str], set[str]] = {}
    for f in facts["edges"]:
        a, b = owner.get(f["src"]), owner.get(f["dst"])
        if (kinds is None or f["kind"] in kinds) and a and b and a != b and frozenset((a, b)) not in covered:
            seen.setdefault((a, b, f["kind"]), set()).add(f"{f['id']} {f.get('detail', '')}".strip())
    return [f"{a} -> {b} [{k}] {'; '.join(sorted(d))}" for (a, b, k), d in sorted(seen.items())]


def _isolated_report(ids: list[str], unshown: list[str]) -> list[str]:
    def ends(line: str) -> set[str]:
        return set(line.split(" [")[0].split(" -> "))

    return [
        f"{i}: " + ("; ".join(u for u in unshown if i in ends(u)) or "no fact connects it") for i in ids
    ]


def _mismatches(edges: list[dict], facts_by_id: dict) -> list[str]:
    out = []
    for e in edges:
        kinds = [facts_by_id[ev["fact"]]["kind"] for ev in e["evidence"] if "fact" in ev]
        has_code = any("file" in ev for ev in e["evidence"])
        if has_code and "iam" not in kinds:
            out.append(f"{e['src']} -> {e['dst']}: code-only, no iam fact backs it")
        elif "iam" in kinds and not has_code:
            out.append(f"{e['src']} -> {e['dst']}: iam-only, no code call site cited")
    return sorted(out)


def verify(facts: dict, curated: dict, repo_root: Path) -> tuple[dict, str]:
    addresses = {r["address"] for r in facts["resources"]}
    facts_by_id = {f["id"]: f for f in facts["edges"]}
    out = json.loads(json.dumps(curated))
    notes: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    dropped_nodes, kept_nodes = [], []
    for n in out["nodes"]:
        missing = sorted(set(n["tf"]) - addresses)
        if contains_secret(n):
            dropped_nodes.append(f"{n['id']}: {SECRET_REASON}")
        elif not n["tf"]:
            dropped_nodes.append(f"{n['id']}: needs at least one tf address")
        elif missing:
            dropped_nodes.append(f"{n['id']}: unknown tf address {', '.join(missing)}")
        elif reason := claim_id(seen, n["id"]):
            dropped_nodes.append(f"{n['id']}: {reason}")
        else:
            kept_nodes.append(n)
            warnings += shape_warnings(n)
    out["nodes"] = kept_nodes

    dropped_externals, kept_externals = [], []
    for x in out["externals"]:
        if contains_secret(x):
            dropped_externals.append(f"{x['id']}: {SECRET_REASON}")
            continue
        warnings += shape_warnings(x)
        good, why = _check_evidence(x["evidence"], facts_by_id, repo_root, set(), set())
        if reason := claim_id(seen, x["id"]):
            dropped_externals.append(f"{x['id']}: {reason}")
        elif good:
            kept_externals.append({**x, "evidence": good})
        else:
            dropped_externals.append(f"{x['id']}: " + "; ".join(why or ["no evidence"]))
    out["externals"] = kept_externals

    tf_of = {n["id"]: set(n["tf"]) for n in kept_nodes} | {x["id"]: set() for x in kept_externals}
    dropped_edges, kept_edges = [], []
    for e in out["edges"]:
        name = f"{e['src']} -> {e['dst']}"
        if contains_secret(e):
            dropped_edges.append(f"{name}: {SECRET_REASON}")
            continue
        gone = [end for end in (e["src"], e["dst"]) if end not in tf_of]
        if gone:
            dropped_edges.append(f"{name}: endpoint dropped or unknown ({', '.join(gone)})")
            continue
        good, why = _check_evidence(e["evidence"], facts_by_id, repo_root, tf_of[e["src"]], tf_of[e["dst"]])
        if good:
            kept_edges.append({**e, "evidence": good})
        else:
            dropped_edges.append(f"{name}: " + "; ".join(why or ["no evidence"]))
    out["edges"] = kept_edges

    fix_groups(out, notes)
    out["assumptions"], bad_assumptions = check_assumptions(curated, set(tf_of), kept_edges)
    covered = {frozenset((e["src"], e["dst"])) for e in kept_edges}
    unshown = _unshown(facts, kept_nodes, covered)
    isolated = _isolated_report(isolated_ids(out), _unshown(facts, kept_nodes, covered, kinds=None))
    mism = _mismatches(kept_edges, facts_by_id)
    ignored = unaccounted(facts.get("hints", []), kept_externals, curated.get("omitted", []))
    dropped = len(dropped_nodes) + len(dropped_externals) + len(dropped_edges) + len(bad_assumptions)
    summary = (
        f"verify: nodes {len(kept_nodes)}/{len(curated['nodes'])}, externals {len(kept_externals)}/"
        f"{len(curated['externals'])}, edges {len(kept_edges)}/{len(curated['edges'])}, dropped {dropped}, "
        f"unshown {len(unshown)}, isolated {len(isolated)}, unaccounted hints {len(ignored)}, mismatches {len(mism)}, warnings {len(warnings) + len(notes)}"
    )
    sections = [
        ("Dropped nodes", dropped_nodes),
        ("Dropped externals", dropped_externals),
        ("Dropped edges", dropped_edges),
        ("Dropped assumptions", bad_assumptions),
        ("Unshown facts (recall hints)", unshown),
        ("Isolated nodes", isolated),
        ("Unaccounted integration hints", ignored),
        ("Code vs IAM mismatches", mism),
        ("Warnings", warnings + notes),
    ]
    return out, render_report(summary, sections)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_root", type=Path)
    ap.add_argument("facts", type=Path)
    ap.add_argument("curated", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything was dropped or a node has no edge")
    args = ap.parse_args()

    curated = json.loads(args.curated.read_text())
    verified, report = verify(json.loads(args.facts.read_text()), curated, args.repo_root)
    args.output.write_text(json.dumps(verified, indent=2, sort_keys=True) + "\n")
    sys.stdout.write(report)
    return 1 if args.strict and needs_attention(curated, verified) else 0


if __name__ == "__main__":
    sys.exit(main())
