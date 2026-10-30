"""Stage 3: check a curated diagram against facts.json and the repo; drop what cannot be proven."""

import argparse
import json
import sys
from pathlib import Path

from cartographer.secret_patterns import contains_secret
from cartographer.tf_blocks import empty_blocks
from cartographer.tf_hint_check import unaccounted

CODE_WINDOW = 3
HINT_KINDS = ("iam", "trigger", "route")
SECRET_REASON = "looks like a secret"


def _code_hit(repo_root: Path, ev: dict) -> str | None:
    """None when the citation checks out, else the reason it does not."""
    path = repo_root / ev["file"]
    if not path.is_file():
        return f"file not found: {ev['file']}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(ev["line"] - 1 - CODE_WINDOW, 0), ev["line"] + CODE_WINDOW
    if any(ev["contains"] in line for line in lines[lo:hi]):
        return None
    return f"{ev['file']}:{ev['line']} does not contain {ev['contains']!r}"


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
        reason = (
            _fact_hit(facts_by_id.get(ev["fact"]), ev["fact"], src_tf, dst_tf)
            if "fact" in ev
            else _code_hit(repo_root, ev)
        )
        if reason is None:
            good.append(ev)
        else:
            why.append(reason)
    return good, why


def _fix_groups(curated: dict, notes: list[str]) -> None:
    ids = {g["id"] for g in curated["groups"]}
    for g in curated["groups"]:
        if g["parent"] is not None and g["parent"] not in ids:
            notes.append(f"group {g['id']}: unknown parent {g['parent']}, moved to top level")
            g["parent"] = None
    for item in curated["nodes"]:
        if item["group"] is not None and item["group"] not in ids:
            notes.append(f"{item['id']}: unknown group {item['group']}, ungrouped")
            item["group"] = None
    notes += [f"group {gid}: no nodes, the layout drops it" for gid in empty_blocks(curated)]


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


def _isolated_ids(diagram: dict) -> list[str]:
    linked = {end for e in diagram["edges"] for end in (e["src"], e["dst"])}
    return sorted(i["id"] for i in (*diagram["nodes"], *diagram["externals"]) if i["id"] not in linked)


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
    from cartographer.diagram_model import AWS_ICONS, BRAND_ICONS, GENERIC_ICONS

    addresses = {r["address"] for r in facts["resources"]}
    facts_by_id = {f["id"]: f for f in facts["edges"]}
    out = json.loads(json.dumps(curated))
    notes: list[str] = []
    warnings: list[str] = []

    dropped_nodes, kept_nodes = [], []
    for n in out["nodes"]:
        missing = sorted(set(n["tf"]) - addresses)
        if contains_secret(n):
            dropped_nodes.append(f"{n['id']}: {SECRET_REASON}")
        elif missing:
            dropped_nodes.append(f"{n['id']}: unknown tf address {', '.join(missing)}")
        else:
            kept_nodes.append(n)
            if n["service"] not in AWS_ICONS and n["service"] != "other":
                warnings.append(f"{n['id']}: service {n['service']!r} is not a draw.io AWS icon, renders as a box")
            if n.get("icon", "none") not in (*GENERIC_ICONS, *BRAND_ICONS, "none"):
                warnings.append(f"{n['id']}: icon {n['icon']!r} is not a draw.io generic or brand shape, renders as a box")
    out["nodes"] = kept_nodes

    dropped_externals, kept_externals = [], []
    for x in out["externals"]:
        if contains_secret(x):
            dropped_externals.append(f"{x['id']}: {SECRET_REASON}")
            continue
        if x.get("icon", "none") not in (*GENERIC_ICONS, *BRAND_ICONS, "none"):
            warnings.append(f"{x['id']}: icon {x['icon']!r} is not a draw.io generic or brand shape, renders as a box")
        good, why = _check_evidence(x["evidence"], facts_by_id, repo_root, set(), set())
        if good:
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

    _fix_groups(out, notes)
    covered = {frozenset((e["src"], e["dst"])) for e in kept_edges}
    unshown = _unshown(facts, kept_nodes, covered)
    isolated = _isolated_report(_isolated_ids(out), _unshown(facts, kept_nodes, covered, kinds=None))
    mism = _mismatches(kept_edges, facts_by_id)
    ignored = unaccounted(facts.get("hints", []), kept_externals, curated.get("omitted", []))
    dropped = len(dropped_nodes) + len(dropped_externals) + len(dropped_edges)
    summary = (
        f"verify: nodes {len(kept_nodes)}/{len(curated['nodes'])}, externals {len(kept_externals)}/"
        f"{len(curated['externals'])}, edges {len(kept_edges)}/{len(curated['edges'])}, dropped {dropped}, "
        f"unshown {len(unshown)}, isolated {len(isolated)}, unaccounted hints {len(ignored)}, mismatches {len(mism)}, warnings {len(warnings) + len(notes)}"
    )
    sections = [
        ("Dropped nodes", dropped_nodes),
        ("Dropped externals", dropped_externals),
        ("Dropped edges", dropped_edges),
        ("Unshown facts (recall hints)", unshown),
        ("Isolated nodes", isolated),
        ("Unaccounted integration hints", ignored),
        ("Code vs IAM mismatches", mism),
        ("Warnings", warnings + notes),
    ]
    lines = [summary]
    for title, items in sections:
        lines += ["", f"{title} ({len(items)})"] + [f"  {i}" for i in sorted(items)]
    return out, "\n".join(lines) + "\n"


def needs_attention(curated: dict, verified: dict) -> bool:
    """True when verify dropped a node, external or edge, or left a node without a line."""
    dropped = sum(len(curated[k]) - len(verified[k]) for k in ("nodes", "externals", "edges"))
    return bool(dropped or _isolated_ids(verified))


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
