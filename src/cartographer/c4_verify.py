"""Check a C4 model against its structure, its evidence and the Terraform facts before any diagram is drawn."""

import json
from collections import Counter
from pathlib import Path

from cartographer import c4_views
from cartographer.c4_model import SCHEMA, Model, RollupError, ancestors, elements
from cartographer.secret_patterns import contains_secret
from cartographer.verify_shared import SECRET_REASON, code_hit, shape_warnings

COMPLETE_TYPES = (
    "aws_lambda_function", "aws_ecs_service", "aws_instance", "aws_autoscaling_group", "aws_db_instance",
    "aws_rds_cluster", "aws_dynamodb_table", "aws_s3_bucket", "aws_sqs_queue", "aws_sns_topic",
    "aws_kinesis_stream", "aws_elasticache_cluster", "aws_elasticache_replication_group",
)
REQUIRED = json.loads(SCHEMA.read_text())["required"]
INSIDE = {"container", "component", "code"}
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
        kind, types = r.get("kind", "uses"), {by_id.get(end, {}).get("type") for end in (r["src"], r["dst"])}
        if kind != "uses" and types != {"code"}:
            out.append(f"{r['id']}: kind {kind} is only for code elements")
        if not r.get("label", "").strip():
            out.append(f"{r['id']}: needs a label")
        # The technology or protocol of a call inside the system; an inheritance arrow states a type, not a call.
        if kind == "uses" and types <= INSIDE and not r.get("technology"):
            out.append(f"{r['id']}: needs a technology, both ends are inside the system")
    out += [f"{s['id']}: step {step} is not a relationship" for s in model.get("scenarios", []) for step in s["steps"]
            if step not in rels]
    out += [w for n in _nodes(model) for w in shape_warnings(n)]
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
    container = _container_of(model, eid)
    hosting = {i["node"] for i in _instances(model) if i["container"] == container}
    return {a for n in _nodes(model) if n["id"] in hosting for a in n.get("tf", [])}


def _joins(fact: dict, ends: tuple[set[str], ...]) -> bool:
    """The fact's src and dst, in either order, land on the host sets in `ends`: none for a deployment node, the
    hosts of an element, or the hosts of a relationship's two ends. An empty set is an end not deployed in this
    environment (or never deployed, like a person), so there is nothing to land on and any address will do."""
    src, dst = fact.get("src"), fact.get("dst")
    return any(all(not hosts or a in hosts for a, hosts in zip(pair, ends)) for pair in ((src, dst), (dst, src)))


def _evidence(item: dict, known: dict[str, dict] | None, repo: Path, ends: tuple[set[str], ...]) -> list[str]:
    """Problems with item's evidence; known maps fact ids to facts, None without facts."""
    out = []
    for ev in item["evidence"]:
        if "fact" in ev and known is None:
            out.append(f"{item['id']}: fact {ev['fact']} needs Terraform facts")
        elif "fact" in ev and ev["fact"] not in known:
            out.append(f"{item['id']}: fact {ev['fact']} not found")
        elif "fact" in ev and not _joins(known[ev["fact"]], ends):
            out.append(f"{item['id']}: fact {ev['fact']} does not join the deployment nodes hosting it")
        elif "file" in ev and (reason := code_hit(repo, ev)):
            out.append(f"{item['id']}: {reason}")
    return out


def _evidence_rules(model: Model, facts: dict | None, repo: Path) -> list[str]:
    known = None if facts is None else {f["id"]: f for key in ("edges", "vpcs", "placements") for f in facts.get(key, [])}
    hosts = {e["id"]: _hosts(model, e["id"]) for e in model["elements"]}
    out = [p for n in _nodes(model) for p in _evidence(n, known, repo, ())]
    out += [p for e in model["elements"] for p in _evidence(e, known, repo, (hosts[e["id"]],))]
    out += [p for r in model["relationships"]
            for p in _evidence(r, known, repo, (hosts.get(r["src"], set()), hosts.get(r["dst"], set())))]
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


def _drawn(model: Model) -> list[str]:
    """Every rolled-up arrow has a label and every relationship is drawn on a core view; needs a sound model."""
    try:
        core = c4_views.core(model)
    except RollupError as err:
        return [str(err)]
    drawn = {rid for view in core for edge in view.curated["edges"] for rid in edge["relationships"]}
    return [f"{r['id']}: drawn on no Context, Container, Component or Code view" for r in model["relationships"]
            if r["id"] not in drawn]


def verify(model: Model, facts: dict | None, repo: Path) -> list[str]:
    """Every problem found, sorted; empty means the model passes. facts is None for source description."""
    missing = [f"model: {key} is required" for key in REQUIRED if key not in model]
    if missing:
        return sorted(missing)
    parents = _parents(model)
    # Ancestor walks loop or raise on broken parent links, so the later rules wait until the parents are sound,
    # and the views are projected only from a model that passes everything else.
    errors = _ids(model) + parents + _structure(model) + _secrets(model)
    if not parents:
        errors += _nesting(model) + _evidence_rules(model, facts, repo) + _deployment(model, facts)
    return sorted(set(errors)) or _drawn(model)


def stated_only(model: Model) -> list[str]:
    """Containers, components, code elements, relationships and deployment nodes whose only evidence is what the
    engineer said; safe on any model."""
    items = [*(e for e in model.get("elements", []) if e["type"] in INSIDE), *model.get("relationships", []),
             *_nodes(model)]
    return sorted(i["id"] for i in items if all("stated" in ev for ev in i["evidence"]))


def report(errors: list[str], stated: list[str]) -> str:
    lines = [f"C4 model: {len(errors)} problems" if errors else "C4 model: ok", *errors]
    if stated:
        lines += ["", f"{STATED_HEADING} ({len(stated)})", *[f"  {i}" for i in stated]]
    return "\n".join(lines) + "\n"
