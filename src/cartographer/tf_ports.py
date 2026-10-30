"""Ports: which side of its node each edge end uses, and where along that side.

An end prefers the side that faces the other end. A side that is full (`capacity`) or crowded gives way to a
neighbouring side, an end prefers a side that already carries its flow colour, and on each side ports are ordered so
that one colour sits together. An icon and its label are one unit: its bottom ports sit under the label.
"""

from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from itertools import pairwise
from math import hypot
from statistics import mean

from cartographer.diagram_model import Edge, Icon, Point, Port
from cartographer.tf_geom import (
    PORT_EDGE,
    PORT_GAP,
    SIDES,
    Leaf,
    body,
    capacity,
    caption_size,
    label_size,
    port_xy,
    side_size,
)

STUB = 14  # how far an edge runs straight out of its port
LOAD, SAME_FLOW, BELOW = 0.4, 0.3, 0.1  # cost of each port already on a side, of a new flow colour, of an icon's bottom
NORMAL = {"R": (1, 0), "L": (-1, 0), "B": (0, 1), "T": (0, -1)}
FRAC: dict[str, Port] = {"L": (0, 0.5), "R": (1, 0.5), "T": (0.5, 0), "B": (0.5, 1)}


@dataclass(frozen=True)
class Anchor:
    node: str
    side: str
    x: int
    y: int
    frac: Port
    off: Point


@dataclass(frozen=True)
class _End:
    edge: int
    end: int
    node: str
    other: Leaf
    colour: str
    heading: tuple[float, float]


def _centre(node: Leaf) -> tuple[float, float]:
    x0, y0, x1, y1 = body(node)
    return (x0 + x1) / 2, (y0 + y1) / 2


def _headings(src: Leaf, dst: Leaf, caption: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Unit vectors from each end towards the other. Side by side but too close for the caption between them: both
    head up, so the edge goes over the top."""
    (sx, sy), (dx, dy) = _centre(src), _centre(dst)
    vx, vy = dx - sx, dy - sy
    if abs(vx) >= abs(vy) and abs(vx) - sum(body(n)[2] - body(n)[0] for n in (src, dst)) / 2 < caption + 2 * STUB:
        return (0, -1), (0, -1)
    n = hypot(vx, vy) or 1
    return (vx / n, vy / n), (-vx / n, -vy / n)


def _penalty(end: _End, node: Leaf, side: str) -> float:
    nx, ny = NORMAL[side]
    return 1 - (nx * end.heading[0] + ny * end.heading[1]) + (BELOW if side == "B" and isinstance(node, Icon) else 0)


def _cost(end: _End, node: Leaf, load: dict, flows: dict, side: str) -> tuple[float, int]:
    key = (end.node, side)
    return (_penalty(end, node, side) + LOAD * load[key] - SAME_FLOW * (end.colour in flows[key]), SIDES.index(side))


def _along(end: _End, axis: int) -> float:
    return _centre(end.other)[axis]


def _assign(ends: list[_End], nodes: dict[str, Leaf]) -> dict[tuple[int, int], str]:
    load: dict[tuple[str, str], int] = defaultdict(int)
    flows: dict[tuple[str, str], set[str]] = defaultdict(set)
    chosen: dict[tuple[int, int], str] = {}
    for end in sorted(ends, key=lambda e: (min(_penalty(e, nodes[e.node], s) for s in SIDES), e.edge, e.end)):
        node = nodes[end.node]
        fill = {s: load[end.node, s] / capacity(node, s) for s in SIDES}
        room = [s for s in SIDES if fill[s] < 1] or [s for s in SIDES if fill[s] == min(fill.values())]

        side = min(room, key=partial(_cost, end, node, load, flows))
        chosen[end.edge, end.end] = side
        load[end.node, side] += 1
        flows[end.node, side].add(end.colour)
    return chosen


def _spread(leaf: Leaf, side: str, ends: list[tuple[int, int]]) -> dict[tuple[int, int], Anchor]:
    """Anchors for the ends on one side, in the given order, PORT_GAP apart and centred on the side."""
    n, along = len(ends), side in "LR"
    step = min(PORT_GAP, (side_size(leaf, side) - 2 * PORT_EDGE) / (n - 1)) if n > 1 else 0
    depth = label_size(leaf.label)[1] if side == "B" and isinstance(leaf, Icon) else 0
    out = {}
    for k, key in enumerate(ends):
        o = round((k - (n - 1) / 2) * step)
        off = (0, o) if along else (o, depth)
        x, y = port_xy(leaf, FRAC[side], off)
        out[key] = Anchor(leaf.id, side, x, y, FRAC[side], off)
    return out


def _by_colour(keys: dict[tuple[int, int], tuple], colour: dict[tuple[int, int], str]) -> list[tuple[int, int]]:
    """Ends sorted by key, each colour kept together at the mean rank of its ends."""
    rank = {e: r for r, e in enumerate(sorted(keys, key=lambda e: (keys[e], e)))}
    centre = {c: mean(rank[e] for e in keys if colour[e] == c) for c in {colour[e] for e in keys}}
    return sorted(keys, key=lambda e: (centre[colour[e]], colour[e], rank[e]))


Pair = tuple[Anchor, Anchor]


def anchors(edges: tuple[Edge, ...], nodes: dict[str, Leaf]) -> list[Pair]:
    """One (source, target) anchor pair per edge; on each side ordered by where the other end sits."""
    ends: list[_End] = []
    for i, e in enumerate(edges):
        hs, hd = _headings(nodes[e.src], nodes[e.dst], caption_size(e.label)[0])
        ends += [_End(i, 0, e.src, nodes[e.dst], e.color, hs), _End(i, 1, e.dst, nodes[e.src], e.color, hd)]
    chosen = _assign(ends, nodes)
    users: dict[tuple[str, str], list[_End]] = defaultdict(list)
    for end in ends:
        users[end.node, chosen[end.edge, end.end]].append(end)
    placed: dict[tuple[int, int], Anchor] = {}
    for (node, side), group in users.items():
        axis = 1 if side in "LR" else 0
        keys = {(e.edge, e.end): (_along(e, axis),) for e in group}
        placed |= _spread(nodes[node], side, _by_colour(keys, {(e.edge, e.end): e.colour for e in group}))
    return [(placed[i, 0], placed[i, 1]) for i in range(len(edges))]


def _turn(anchor: Anchor, outward: list[Point]) -> tuple[int, int]:
    """Which way a route bends off its port's line (-1 towards the side's start, 1 towards its end, 0 never), and
    how far out: bending the same way, the end nearer the bend's side bends nearest the node."""
    axis = 1 if anchor.side in "LR" else 0
    start = outward[0]
    for prev, p in pairwise(outward):
        if p[axis] != start[axis]:
            sign = 1 if p[axis] > start[axis] else -1
            out = abs(prev[1 - axis] - start[1 - axis])
            return sign, -out if sign > 0 else out
    return 0, 0


def untangle(edges: tuple[Edge, ...], nodes: dict[str, Leaf], pairs: list[Pair], polys: list[list[Point]]) -> list[Pair]:
    """The same sides with the ports on each reordered the way the routes leave them, so that routes bending the
    same way do not cross or run over each other's stubs next to the node."""
    keys: dict[tuple[str, str], dict[tuple[int, int], tuple]] = defaultdict(dict)
    for i, (pair, poly) in enumerate(zip(pairs, polys)):
        for end, (anchor, outward) in enumerate(((pair[0], poly), (pair[1], poly[::-1]))):
            keys[anchor.node, anchor.side][i, end] = (*_turn(anchor, outward[1:]), pairs[i][end].off)
    placed: dict[tuple[int, int], Anchor] = {}
    for (node, side), group in keys.items():
        placed |= _spread(nodes[node], side, _by_colour(group, {e: edges[e[0]].color for e in group}))
    return [(placed[i, 0], placed[i, 1]) for i in range(len(edges))]
