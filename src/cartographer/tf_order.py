"""Barycentric ordering: reorder nodes, blocks and externals by where their neighbours sit in a first placement."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from cartographer.diagram_model import ICON, Diagram, Group, Icon, bounds
from cartographer.tf_blocks import FRAMES

Curated = dict[str, Any]
Point = tuple[float, float]


def _centre(node: Group | Icon | Any) -> Point:
    x0, y0, x1, y1 = bounds(node)
    if isinstance(node, Icon):
        y1 = y0 + ICON
    return (x0 + x1) / 2, (y0 + y1) / 2


def centres(diagram: Diagram) -> dict[str, Point]:
    """Centre of every placed item; an icon's centre is that of its 60 px shape, not of the label below."""
    return {n.id: _centre(n) for n in diagram.nodes}


def _mean(points: list[float], default: float) -> float:
    return sum(points) / len(points) if points else default


def _resort(items: list[dict], slot: Callable[[dict], Any], key: Callable[[dict], float]) -> list[dict]:
    """Items sharing a slot trade places, sorted by (key, id); the list order across slots is unchanged."""
    slots: dict[Any, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        slots[slot(item)].append(i)
    out = list(items)
    for idxs in slots.values():
        for i, item in zip(idxs, sorted((items[j] for j in idxs), key=lambda it: (key(it), it["id"]))):
            out[i] = item
    return out


def reorder(curated: Curated, diagram: Diagram) -> Curated:
    """One barycentric pass: nodes by mean neighbour x, blocks and externals by mean neighbour y."""
    pos = centres(diagram)
    near: dict[str, set[str]] = defaultdict(set)
    for e in curated["edges"]:
        if e["src"] != e["dst"] and e["src"] in pos and e["dst"] in pos:
            near[e["src"]].add(e["dst"])
            near[e["dst"]].add(e["src"])

    def along(axis: int, ids: set[str], own: str) -> float:
        return _mean([pos[i][axis] for i in ids], pos.get(own, (0, 0))[axis])

    parent = {g["id"]: g["parent"] for g in curated["groups"]}
    inside: dict[str, set[str]] = defaultdict(set)
    for n in curated["nodes"]:
        gid = n["group"]
        while gid in parent and n["id"] not in inside[gid]:
            inside[gid].add(n["id"])
            gid = parent[gid]
    blocks = {g["id"] for g in curated["groups"] if g["kind"] not in FRAMES}

    def block_slot(g: dict) -> Any:
        if g["kind"] in FRAMES:
            return g["id"]
        return g["parent"], (0 if g["parent"] in blocks else g["column"])

    def block_key(g: dict) -> float:
        outside = {o for m in inside[g["id"]] for o in near[m]} - inside[g["id"]]
        return along(1, outside, g["id"])

    return {
        **curated,
        "nodes": _resort(curated["nodes"], lambda n: n["group"], lambda n: along(0, near[n["id"]], n["id"])),
        "groups": _resort(curated["groups"], block_slot, block_key),
        "externals": _resort(curated["externals"], lambda x: 0, lambda x: along(1, near[x["id"]], x["id"])),
    }
