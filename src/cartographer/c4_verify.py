"""Check a C4 model against its structure, its evidence and the Terraform facts before any diagram is drawn."""

import json
from collections import Counter
from pathlib import Path

from cartographer.c4_model import SCHEMA, Model, ancestors, elements
from cartographer.secret_patterns import contains_secret
from cartographer.verify_shared import SECRET_REASON, code_hit

COMPLETE_TYPES = (
    "aws_lambda_function", "aws_ecs_service", "aws_instance", "aws_autoscaling_group", "aws_db_instance",
    "aws_rds_cluster", "aws_dynamodb_table", "aws_s3_bucket", "aws_sqs_queue", "aws_sns_topic",
    "aws_kinesis_stream", "aws_elasticache_cluster", "aws_elasticache_replication_group",
)
REQUIRED = json.loads(SCHEMA.read_text())["required"]
PARENT_TYPE = {"container": "system", "component": "container", "code": "component"}
STATED_HEADING = "Stated by the engineer, not found in the repo"


def _nodes(model: Model) -> list[dict]:
    return model.get("deployment", {}).get("nodes", [])


def _instances(model: Model) -> list[dict]:
    return model.get("deployment", {}).get("instances", [])


def _ids(model: Model) -> list[str]:
    scenarios = model.get("scenarios", [])
    seen = Counter(i["id"] for part in (model["elements"], model["relationships"], _nodes(model), scenarios) for i in part)
    return [f"{i}: duplicate id" for i, n in seen.items() if n > 1]


def _cyclic(by_id: dict[str, dict], eid: str) -> bool:
    seen = set()
    while eid in by_id and eid not in seen:
        seen.add(eid)
        eid = by_id[eid].get("parent")
    return eid in seen


def _parents(model: Model) -> list[str]:
    """Parent links that cannot be followed or are the wrong type; safe on any model."""
    by_id, out = elements(model), []
    for e in model["elements"]:
        parent, want = e.get("parent"), PARENT_TYPE.get(e["type"])
        if parent is not None and parent not in by_id:
            out.append(f"{e['id']}: parent {parent} does not exist")
        elif want and (parent is None or by_id[parent]["type"] != want):
            out.append(f"{e['id']}: {e['type']} needs a {want} as parent")
        elif not want and parent is not None:
            out.append(f"{e['id']}: {e['type']} has no parent")
        if _cyclic(by_id, e["id"]):
            out.append(f"{e['id']}: parent cycle")
    return out


def _structure(model: Model) -> list[str]:
    by_id, out = elements(model), []
    systems = [e for e in model["elements"] if e["type"] == "system" and not e.get("external")]
    if len(systems) != 1:
        out.append(f"model: exactly one in-scope system is needed, found {len(systems)}")
    out += [f"{e['id']}: {e['type']} needs a technology" for e in model["elements"]
            if e["type"] in ("container", "component") and not e.get("technology")]
    rels = {r["id"] for r in model["relationships"]}
    for r in model["relationships"]:
        out += [f"{r['id']}: unknown end {end}" for end in (r["src"], r["dst"]) if end not in by_id]
        if r["src"] == r["dst"]:
            out.append(f"{r['id']}: ends are the same element")
        kind = r.get("kind", "uses")
        if kind != "uses" and not all(by_id.get(end, {}).get("type") == "code" for end in (r["src"], r["dst"])):
            out.append(f"{r['id']}: kind {kind} is only for code elements")
    out += [f"{s['id']}: step {step} is not a relationship" for s in model.get("scenarios", []) for step in s["steps"]
            if step not in rels]
    node_ids = {n["id"] for n in _nodes(model)}
    for i in _instances(model):
        if i["container"] not in by_id:
            out.append(f"{i['container']}: instance container does not exist")
        if i["node"] not in node_ids:
            out.append(f"{i['container']}: instance node {i['node']} does not exist")
    out += [f"{n['id']}: parent {n['parent']} does not exist" for n in _nodes(model)
            if n.get("parent") not in (None, *node_ids)]
    return out


def _container_of(model: Model, eid: str) -> str | None:
    by_id = elements(model)
    return next((e for e in [eid, *ancestors(model, eid)] if by_id[e]["type"] == "container"), None)


def _nesting(model: Model) -> list[str]:
    """Relationships a view could not draw: between an element and its own ancestor, ending at a system that has
    containers, or (as a scenario step) staying inside one container; needs sound parent links."""
    by_id = elements(model)
    known = [r for r in model["relationships"] if r["src"] in by_id and r["dst"] in by_id]
    out = [f"{r['id']}: ends are ancestor and descendant" for r in known
           if r["dst"] in ancestors(model, r["src"]) or r["src"] in ancestors(model, r["dst"])]
    systems = [e["id"] for e in model["elements"] if e["type"] == "system" and not e.get("external")]
    split = {e["parent"] for e in model["elements"] if e["type"] == "container"} & set(systems)
    out += [f"{r['id']}: ends at the system {end}; name the container it reaches"
            for r in known for end in (r["src"], r["dst"]) if end in split]
    steps = {r["id"]: r for r in known}
    for s in model.get("scenarios", []):
        for step in s["steps"]:
            inner = {_container_of(model, steps[step][end]) for end in ("src", "dst")} if step in steps else set()
            if len(inner) == 1 and None not in inner:
                out.append(f"{s['id']}: step {step} stays inside container {inner.pop()}")
    return out


def _hosts(model: Model, eid: str) -> set[str]:
    """Terraform addresses of the nodes hosting the container that eid is, or sits in."""
    by_id = elements(model)
    container = next((e for e in [eid, *ancestors(model, eid)] if by_id[e]["type"] == "container"), None)
    hosting = {i["node"] for i in _instances(model) if i["container"] == container}
    return {a for n in _nodes(model) if n["id"] in hosting for a in n.get("tf", [])}


def _joins(ends: tuple[set[str], set[str]], fact: dict) -> bool:
    """True when the fact's src and dst sit on the hosts of the two ends, in either direction."""
    src, dst = fact.get("src"), fact.get("dst")
    return src in ends[0] and dst in ends[1] or src in ends[1] and dst in ends[0]


def _evidence(item: dict, known: dict[str, dict] | None, repo: Path, ends: tuple[set[str], set[str]] | None = None) -> list[str]:
    """Problems with item's evidence; known maps fact ids to facts, None without facts."""
    out = []
    for ev in item["evidence"]:
        if "fact" in ev and known is None:
            out.append(f"{item['id']}: fact {ev['fact']} needs Terraform facts")
        elif "fact" in ev and ev["fact"] not in known:
            out.append(f"{item['id']}: fact {ev['fact']} not found")
        elif "fact" in ev and ends and not _joins(ends, known[ev["fact"]]):
            out.append(f"{item['id']}: fact {ev['fact']} does not join the nodes hosting its two ends")
        elif "file" in ev and (reason := code_hit(repo, ev)):
            out.append(f"{item['id']}: {reason}")
    return out


def _evidence_rules(model: Model, facts: dict | None, repo: Path) -> list[str]:
    known = None if facts is None else {f["id"]: f for key in ("edges", "vpcs", "placements") for f in facts.get(key, [])}
    by_id = elements(model)
    out = [e for item in (*model["elements"], *_nodes(model)) for e in _evidence(item, known, repo)]
    for r in model["relationships"]:
        ends = (_hosts(model, r["src"]), _hosts(model, r["dst"])) if r["src"] in by_id and r["dst"] in by_id else None
        out += _evidence(r, known, repo, ends)
    return out


def _deployment(model: Model, facts: dict | None) -> list[str]:
    """Terraform sources: every infrastructure node (frames are optional) names addresses that exist in the facts,
    and every compute or storage resource is on a node or omitted."""
    if model["source"] != "terraform" or facts is None:
        return []
    addresses = {r["address"] for r in facts["resources"]}
    out = [f"{n['id']}: needs terraform addresses" for n in _nodes(model) if not n.get("tf") and "frame" not in n]
    out += [f"{n['id']}: {a} is not in the facts" for n in _nodes(model) for a in n.get("tf", []) if a not in addresses]
    placed = {a for n in _nodes(model) for a in n.get("tf", [])} | {o["tf"] for o in model.get("omitted", [])}
    out += [f"{r['address']}: not on any view and not omitted" for r in facts["resources"]
            if r["type"] in COMPLETE_TYPES and r["address"] not in placed]
    return out


def _secrets(model: Model) -> list[str]:
    items = [(i["id"], i) for i in (*model["elements"], *model["relationships"], *_nodes(model))]
    items += [(a["about"], a) for a in model.get("assumptions", [])]
    return [f"{i}: {SECRET_REASON}" for i, item in items if contains_secret(item)]


def verify(model: Model, facts: dict | None, repo: Path) -> list[str]:
    """Every problem found, sorted; empty means the model passes. facts is None for source description."""
    missing = [f"model: {key} is required" for key in REQUIRED if key not in model]
    if missing:
        return sorted(missing)
    parents = _parents(model)
    # Ancestor walks loop or raise on broken parent links, so the later rules wait until the parents are sound.
    errors = _ids(model) + parents + _structure(model) + _secrets(model)
    if not parents:
        errors += _nesting(model) + _evidence_rules(model, facts, repo) + _deployment(model, facts)
    return sorted(set(errors))


def stated_only(model: Model) -> list[str]:
    """Containers, components and code elements whose only evidence is what the engineer said; safe on any model."""
    return sorted(e["id"] for e in model.get("elements", [])
                  if e["type"] in ("container", "component", "code") and all("stated" in ev for ev in e["evidence"]))


def report(errors: list[str], stated: list[str]) -> str:
    lines = [f"C4 model: {len(errors)} problems" if errors else "C4 model: ok", *errors]
    if stated:
        lines += ["", f"{STATED_HEADING} ({len(stated)})", *[f"  {i}" for i in stated]]
    return "\n".join(lines) + "\n"
