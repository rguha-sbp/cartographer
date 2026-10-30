"""Check a curated diagram that was described by an engineer: structure and stated or cited evidence, no facts."""

import json
from pathlib import Path

from cartographer.secret_patterns import contains_secret
from cartographer.verify_shared import (
    SECRET_REASON,
    check_assumptions,
    claim_id,
    code_hit,
    edge_name,
    fix_groups,
    isolated_ids,
    render_report,
    shape_warnings,
)

STATED_MAX = 200


def _evidence_problem(ev: dict, repo_root: Path) -> str | None:
    if "fact" in ev:
        return "fact evidence is for Terraform diagrams"
    if "stated" in ev:
        return None if len(ev["stated"]) <= STATED_MAX else f"stated evidence is over {STATED_MAX} characters"
    return code_hit(repo_root, ev)


def _supported(evidence: list[dict], repo_root: Path) -> tuple[list[dict], list[str]]:
    good, why = [], []
    for ev in evidence:
        problem = _evidence_problem(ev, repo_root)
        if problem is None:
            good.append(ev)
        else:
            why.append(problem)
    return good, why or ([] if good else ["no evidence"])


def _node_problem(node: dict, seen: set[str]) -> str | None:
    if contains_secret(node):
        return SECRET_REASON
    if node["tf"]:
        return "tf addresses are for Terraform diagrams"
    return claim_id(seen, node["id"])


def verify(curated: dict, repo_root: Path) -> tuple[dict, str]:
    out = json.loads(json.dumps(curated))
    seen: set[str] = set()
    dropped: dict[str, list[str]] = {"nodes": [], "externals": [], "edges": []}
    warnings: list[str] = []

    kept_nodes = []
    for n in out["nodes"]:
        problem = _node_problem(n, seen)
        if problem:
            dropped["nodes"].append(f"{n['id']}: {problem}")
        else:
            kept_nodes.append(n)
            warnings += shape_warnings(n)
    out["nodes"] = kept_nodes

    kept_externals = []
    for x in out["externals"]:
        good, why = _supported(x["evidence"], repo_root)
        problem = SECRET_REASON if contains_secret(x) else claim_id(seen, x["id"]) or "; ".join(why)
        if problem:
            dropped["externals"].append(f"{x['id']}: {problem}")
        else:
            kept_externals.append({**x, "evidence": good})
            warnings += shape_warnings(x)
    out["externals"] = kept_externals

    ends = {i["id"] for i in (*kept_nodes, *kept_externals)}
    kept_edges = []
    for e in out["edges"]:
        gone = [end for end in (e["src"], e["dst"]) if end not in ends]
        good, why = _supported(e["evidence"], repo_root)
        if contains_secret(e):
            problem = SECRET_REASON
        elif gone:
            problem = f"endpoint dropped or unknown ({', '.join(gone)})"
        else:
            problem = "; ".join(why)
        if problem:
            dropped["edges"].append(f"{edge_name(e)}: {problem}")
        else:
            kept_edges.append({**e, "evidence": good})
    out["edges"] = kept_edges

    notes: list[str] = []
    fix_groups(out, notes)
    out["assumptions"], bad_assumptions = check_assumptions(curated, ends, kept_edges)
    isolated = [f"{i}: no edge connects it" for i in isolated_ids(out)]
    total = sum(map(len, dropped.values())) + len(bad_assumptions)
    summary = (
        f"verify: nodes {len(kept_nodes)}/{len(curated['nodes'])}, externals {len(kept_externals)}/"
        f"{len(curated['externals'])}, edges {len(kept_edges)}/{len(curated['edges'])}, dropped {total}, "
        f"isolated {len(isolated)}, warnings {len(warnings) + len(notes)}"
    )
    return out, render_report(summary, [
        ("Dropped nodes", dropped["nodes"]),
        ("Dropped externals", dropped["externals"]),
        ("Dropped edges", dropped["edges"]),
        ("Dropped assumptions", bad_assumptions),
        ("Isolated nodes", isolated),
        ("Warnings", warnings + notes),
    ])
