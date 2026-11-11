"""What the Terraform and the description verification share: structure checks, code citations and the report."""

from collections.abc import Callable, Iterator
from pathlib import Path

from cartographer import icons
from cartographer.clouds import CLOUDS, resolve_declared
from cartographer.curated_format import FRAME_KINDS
from cartographer.secret_patterns import contains_secret
from cartographer.tf_blocks import empty_blocks

CODE_WINDOW = 3
SECRET_REASON = "looks like a secret"
NETWORK_KINDS = ("network", "subnet")
UNKNOWN_TARGET = "unknown node, external or edge"


def code_hit(repo_root: Path, ev: dict) -> str | None:
    """None when the citation checks out, else the reason it does not."""
    path = repo_root / ev["file"]
    if not path.is_file():
        return f"file not found: {ev['file']}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(ev["line"] - 1 - CODE_WINDOW, 0), ev["line"] + CODE_WINDOW
    if any(ev["contains"] in line for line in lines[lo:hi]):
        return None
    return f"{ev['file']}:{ev['line']} does not contain {ev['contains']!r}"


def claim_id(seen: set[str], item_id: str) -> str | None:
    """Reserve an id for a node or external; the reason when it is taken."""
    if item_id in seen:
        return "duplicate id"
    seen.add(item_id)
    return None


def shape_warnings(item: dict) -> list[str]:
    icon = item.get("icon", "none")
    if icon == "none" or icons.known(icon):
        return []
    return [f"{item['id']}: icon {icon!r} is not a known icon, renders as a box"]


def set_reason(item: dict, reason: str | None) -> None:
    """Keep `reason` only on a marked item, so a re-verified item never carries a stale one."""
    if reason:
        item["reason"] = reason
    else:
        item.pop("reason", None)


def declared_icon(item: dict) -> None:
    """Set `icon`, `decided_by`, `marked` and a marked item's `reason` from the catalog when the item names a
    `tf_type`; an item that names a cloud icon directly is marked as the curator's choice."""
    if tf_type := item.get("tf_type"):
        res = resolve_declared(tf_type, item.get("attributes", {}))
        if res.icon:
            item.update(icon=res.icon, decided_by=res.decided_by, marked=res.marked)
            set_reason(item, res.reason if res.marked else None)
            return
    if icons.cloud_of(item.get("icon", "")):
        item.update(decided_by="curator", marked=True)


def ancestors(groups: dict[str, dict], gid: str | None) -> Iterator[dict]:
    """Group `gid` and the groups it sits inside, innermost first; the walk stops at an unknown id or a parent loop."""
    seen: set[str] = set()
    while gid in groups and gid not in seen:
        seen.add(gid)
        yield groups[gid]
        gid = groups[gid]["parent"]


def frame_cloud(groups: dict[str, dict], gid: str | None) -> str | None:
    """The cloud of the nearest enclosing frame."""
    return next((g.get("cloud") for g in ancestors(groups, gid) if g["kind"] in FRAME_KINDS), None)


def cloud_warnings(diagram: dict) -> list[str]:
    groups = {g["id"]: g for g in diagram["groups"]}
    out = []
    for n in (*diagram["nodes"], *diagram["externals"]):
        icon_cloud, frame = icons.cloud_of(n.get("icon", "")), frame_cloud(groups, n.get("group"))
        if icon_cloud and frame and icon_cloud != frame:
            out.append(f"{n['id']}: icon {n['icon']} belongs to {icon_cloud}, its frame to {frame}")
    return out


def edge_name(edge: dict) -> str:
    return f"{edge['src']}->{edge['dst']}"


def check_assumptions(curated: dict, node_ids: set[str], edges: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep the assumptions that name a kept node, external or edge and hold no secret."""
    targets = node_ids | {edge_name(e) for e in edges}
    kept, dropped = [], []
    for a in curated.get("assumptions", []):
        if contains_secret(a):
            dropped.append(f"{a['about']}: {SECRET_REASON}")
        elif a["about"] not in targets:
            dropped.append(f"{a['about']}: {UNKNOWN_TARGET}")
        else:
            kept.append(a)
    return kept, dropped


def enclosing(groups: dict[str, dict], gid: str | None, kind: str) -> dict | None:
    """The group of `kind` that `gid` is, or sits inside."""
    return next((g for g in ancestors(groups, gid) if g["kind"] == kind), None)


def outside_network(groups: dict[str, dict], group: dict) -> str | None:
    """The nearest ancestor of a network or subnet group that is not a network or subnet frame."""
    return next((g["id"] for g in ancestors(groups, group["parent"]) if g["kind"] not in NETWORK_KINDS), None)


def _demote(group: dict) -> None:
    group["kind"] = None
    group.pop("tier", None)


def fix_clouds(curated: dict, notes: list[str]) -> None:
    """A frame needs the cloud whose styles draw it; without a known one it is a plain group."""
    for g in curated["groups"]:
        if g["kind"] in FRAME_KINDS and g.get("cloud") not in CLOUDS:
            notes.append(f"group {g['id']}: {g['kind']} frame without a known cloud, now a plain group")
            _demote(g)


def fix_network_groups(curated: dict, notes: list[str]) -> None:
    """Drop `tier` and `cidrs` from groups they do not belong to and `external` (and the older `shared_from`), which
    only verify sets, from every group; a subnet group needs a tier and a network parent."""
    groups = {g["id"]: g for g in curated["groups"]}
    for g in curated["groups"]:
        if g["kind"] != "subnet" and "tier" in g:
            notes.append(f"group {g['id']}: tier on a group that is not a subnet, dropped")
            del g["tier"]
        if g["kind"] != "network" and "cidrs" in g:
            notes.append(f"group {g['id']}: cidrs on a group that is not a network, dropped")
            del g["cidrs"]
        for key in ("external", "shared_from"):
            if key in g:
                notes.append(f"group {g['id']}: {key} is set by verify, not the curator, dropped")
                del g[key]
        if g["kind"] == "subnet" and "tier" not in g:
            notes.append(f"group {g['id']}: subnet without a tier, now a plain group")
            _demote(g)
        elif g["kind"] == "subnet" and groups.get(g["parent"], {}).get("kind") != "network":
            notes.append(f"group {g['id']}: subnet parent {g['parent']} is not a network group, now a plain group")
            _demote(g)


Supported = Callable[[dict, list[dict]], tuple[list[dict], list[str]]]


def check_claims(curated: dict, notes: list[str], supported: Supported) -> None:
    """Keep a network group's `cidrs` and a subnet group's tier only while `supported(group, evidence)` finds evidence.
    A network group keeps its evidence when its cidrs drop: it still names the network the group stands for."""
    for g in curated["groups"]:
        if g["kind"] == "network" and not g.get("cidrs") or g["kind"] not in NETWORK_KINDS:
            continue
        good, why = supported(g, g.get("evidence", []))
        if secret := contains_secret(g):
            good, why = [], [SECRET_REASON]
        if g["kind"] == "network":
            if not good:
                notes.append(f"group {g['id']}: cidrs dropped, {'; '.join(why) or 'no evidence'}")
                del g["cidrs"]
            if secret:
                g.pop("evidence", None)
        elif good:
            g["evidence"] = good
        else:
            notes.append(f"group {g['id']}: tier {g['tier']} dropped, {'; '.join(why) or 'no evidence'}")
            _demote(g)
            g.pop("evidence", None)


def group_claims(diagram: dict) -> set[tuple]:
    """Network claims the diagram makes: network cidrs, subnet tiers and parents, nodes inside a network."""
    groups = {g["id"]: g for g in diagram["groups"]}
    claims = {("cidrs", g["id"], tuple(g["cidrs"])) for g in diagram["groups"] if g.get("cidrs")}
    claims |= {("subnet", g["id"], g.get("tier"), g["parent"]) for g in diagram["groups"] if g["kind"] == "subnet"}
    claims |= {("inside", n["id"], n["group"]) for n in diagram["nodes"] if enclosing(groups, n["group"], "network")}
    return claims


def fix_groups(curated: dict, notes: list[str]) -> None:
    ids = {g["id"] for g in curated["groups"]}
    for g in curated["groups"]:
        if g["parent"] is not None and g["parent"] not in ids:
            notes.append(f"group {g['id']}: unknown parent {g['parent']}, moved to top level")
            g["parent"] = None
    for item in curated["nodes"]:
        if item["group"] is not None and item["group"] not in ids:
            notes.append(f"{item['id']}: unknown group {item['group']}, ungrouped")
            item["group"] = None
    fix_clouds(curated, notes)
    fix_network_groups(curated, notes)
    notes += [f"group {gid}: no nodes, the layout drops it" for gid in empty_blocks(curated)]


def isolated_ids(diagram: dict) -> list[str]:
    linked = {end for e in diagram["edges"] for end in (e["src"], e["dst"])}
    return sorted(i["id"] for i in (*diagram["nodes"], *diagram["externals"]) if i["id"] not in linked)


def needs_attention(curated: dict, verified: dict) -> bool:
    """True when verify dropped a node, external, edge, assumption or network claim, or left a node without a line."""
    dropped = sum(len(curated.get(k, [])) - len(verified.get(k, [])) for k in ("nodes", "externals", "edges", "assumptions"))
    return bool(dropped or isolated_ids(verified) or not group_claims(curated) <= group_claims(verified))


def render_report(summary: str, sections: list[tuple[str, list[str]]]) -> str:
    lines = [summary]
    for title, items in sections:
        lines += ["", f"{title} ({len(items)})"] + [f"  {i}" for i in sorted(items)]
    return "\n".join(lines) + "\n"
