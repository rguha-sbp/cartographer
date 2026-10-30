"""Edge routing: orthogonal least-cost paths on a sparse grid of candidate lines, one edge after another.

Nodes (with their labels, kept NODE_CLEAR away) and group titles are walls, and so is every group the edge does not
start or end in. A segment never runs within LINE_GAP of a parallel segment of another edge; only an edge with no
such route is drawn with the clearance broken (counted by `tf_check`). Cost is length plus a penalty per bend, and a
dearer one for crossing an earlier edge or the zone of a placed caption. Edges are routed shortest first, ties by id, so the result is
deterministic. Every route starts and ends with the straight stub out of its port, kept as explicit points.
"""

from dataclasses import replace

from cartographer.diagram_model import Diagram, Point
from cartographer.tf_check import defects
from cartographer.tf_geom import (
    GROUP_CLEAR,
    NODE_CLEAR,
    foreign,
    group_rect,
    groups,
    leaves,
    obstacles,
    polyline,
    segments,
    title_rect,
)
from cartographer.tf_grid import DIRS, Grid
from cartographer.tf_labels import Captions
from cartographer.tf_ports import STUB, Anchor, Pair, anchors, untangle

SIDE_DIR = {"R": 0, "L": 1, "B": 2, "T": 3}


def _simplify(poly: list[Point]) -> list[Point]:
    """Drop repeated points and points in the middle of a straight run."""
    out: list[Point] = []
    for p in poly:
        if out and p == out[-1]:
            continue
        while len(out) > 1 and (out[-2][0] == out[-1][0] == p[0] or out[-2][1] == out[-1][1] == p[1]):
            out.pop()
        out.append(p)
    return out


def _stub(a: Anchor) -> Point:
    dx, dy = DIRS[SIDE_DIR[a.side]]
    return a.x + dx * STUB, a.y + dy * STUB


def route(diagram: Diagram) -> Diagram:
    """The diagram with every edge's ports, bend points and caption position filled in. The first routing shows
    which way each route leaves its port; the ports on every side are reordered to match and the diagram routed
    again, and the one with fewer `defects` is kept."""
    nodes = leaves(diagram)
    titles = [title_rect(g) for g in groups(diagram)]
    ends = anchors(diagram.edges, nodes, titles)
    first = _route(diagram, ends)
    again = _route(diagram, untangle(diagram.edges, nodes, ends, [polyline(e, nodes) for e in first.edges], titles))
    return min((first, again), key=defects)


def _route(diagram: Diagram, ends: list[Pair]) -> Diagram:
    nodes = leaves(diagram)
    edges = diagram.edges
    frames = groups(diagram)
    stubs = [p for pair in ends for a in pair for p in ((a.x, a.y), _stub(a))]
    grid = Grid(obstacles(nodes, NODE_CLEAR) + [title_rect(g) for g in frames],
                [group_rect(g, GROUP_CLEAR) for g in frames], [group_rect(g) for g in frames], stubs)
    for i, pair in enumerate(ends):
        for a in pair:
            grid.reserve((a.x, a.y), _stub(a), i)
    captions = Captions(nodes, frames, [segments([(a.x, a.y), _stub(a)]) + segments([_stub(b), (b.x, b.y)])
                                        for a, b in ends])
    order = sorted(range(len(edges)), key=lambda i: (abs(ends[i][0].x - ends[i][1].x) + abs(ends[i][0].y - ends[i][1].y),
                                                     edges[i].src, edges[i].dst, edges[i].label, i))
    routed = list(edges)
    for i in order:
        a, b = ends[i]
        sa, sb = _stub(a), _stub(b)
        outside = [frames.index(g) for g in foreign(frames, nodes[edges[i].src], nodes[edges[i].dst])]
        path = None
        for hard, beside in ((True, True), (False, True), (False, False)):
            path = grid.route(sa, SIDE_DIR[a.side], sb, grid.blocked(outside, beside), i, hard)
            if path:
                break
        if path:
            grid.commit(path, i)
        middle = _simplify([(grid.xs[x], grid.ys[y]) for x, y in path] if path else [sa, (sb[0], sa[1]), sb])
        poly = [(a.x, a.y), *middle, (b.x, b.y)]
        at, shift, zone = captions.place(i, poly, edges[i].label) if edges[i].label else (0, (0, 0), None)
        captions.add_route(i, poly)
        if zone:
            grid.add_caption(zone)
        routed[i] = replace(edges[i], out=a.frac, into=b.frac, out_off=a.off, into_off=b.off, points=tuple(middle),
                            exact=True, at=at, shift=shift)
    for i in order:
        if edges[i].label and not captions.clear(i):
            at, shift, _ = captions.place(i, polyline(routed[i], nodes), edges[i].label)
            routed[i] = replace(routed[i], at=at, shift=shift)
    return replace(diagram, edges=tuple(routed))
