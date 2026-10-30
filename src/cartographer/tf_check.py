"""Measure a drawn diagram from its draw.io file: how many lines, ports and captions collide or crowd."""

from dataclasses import dataclass, fields
from itertools import combinations, pairwise
from math import hypot

from cartographer.diagram_model import Diagram, Point
from cartographer.tf_geom import (
    CAPTION_CLEAR,
    CAPTION_NEAR,
    LINE_GAP,
    NODE_CLEAR,
    PORT_EDGE,
    PORT_GAP,
    Rect,
    Seg,
    borders,
    crosses,
    foreign,
    group_rect,
    groups,
    inflate,
    leaves,
    obstacles,
    overlap,
    parallel_gap,
    polyline,
    rects,
    segments,
    side_of,
    side_size,
    title_rect,
)
from cartographer.tf_labels import caption_rect
from cartographer.tf_read import read

METRICS = ("edges", "bends", "crossings")


@dataclass(frozen=True)
class RouteStats:
    edges: int
    bends: int
    crossings: int
    caption_overlaps: int
    caption_on_node: int
    edge_through_node: int
    caption_on_line: int
    edge_through_group: int
    edge_through_title: int
    lines_too_close: int
    line_on_frame: int
    ports_too_close: int
    line_near_node: int
    caption_crowding: int
    caption_far: int
    angled_segments: int

    def summary(self) -> str:
        return "route: " + ", ".join(f"{f.name.replace('_', ' ')} {getattr(self, f.name)}" for f in fields(self))

    @property
    def violations(self) -> int:
        return sum(getattr(self, f.name) for f in fields(self) if f.name not in METRICS)


def _crosses(a: Seg, b: Seg) -> bool:
    """A horizontal and a vertical segment that meet strictly inside both."""
    if (a[0][1] == a[1][1]) == (b[0][1] == b[1][1]):
        return False
    h, v = (a, b) if a[0][1] == a[1][1] else (b, a)
    return (min(h[0][0], h[1][0]) < v[0][0] < max(h[0][0], h[1][0])
            and min(v[0][1], v[1][1]) < h[0][1] < max(v[0][1], v[1][1]))


def _turns(poly: list) -> int:
    return sum((b[0] - a[0]) * (c[1] - b[1]) != (b[1] - a[1]) * (c[0] - b[0]) for a, b, c in zip(poly, poly[1:], poly[2:]))


def _ports_too_close(diagram: Diagram) -> int:
    nodes = leaves(diagram)
    sides: dict[tuple[str, str], list[int]] = {}
    for e in diagram.edges:
        for node, port, off in ((e.src, e.out, e.out_off), (e.dst, e.into, e.into_off)):
            side = side_of(port)
            sides.setdefault((node, side), []).append(off[1] if side in "LR" else off[0])
    bad = 0
    for (node, side), pos in sides.items():
        pos.sort()
        bad += sum(b - a < PORT_GAP for a, b in pairwise(pos))
        bad += sum(abs(p) > side_size(nodes[node], side) // 2 - PORT_EDGE for p in pos)
    return bad


def _near_node(diagram: Diagram) -> int:
    """Edges with a segment closer than NODE_CLEAR to a node's shape or label; the first and last segment may touch
    their own node."""
    nodes = leaves(diagram)
    bad = 0
    for e in diagram.edges:
        segs = segments(polyline(e, nodes))
        for k, s in enumerate(segs):
            own = nodes[e.src] if k == 0 else nodes[e.dst] if k == len(segs) - 1 else None
            zones = [r for n in nodes.values() if n is not own for r in rects(n, NODE_CLEAR)]
            if any(crosses(s, z) for z in zones):
                bad += 1
                break
    return bad


def _boxes(diagram: Diagram) -> dict[int, Rect]:
    nodes = leaves(diagram)
    return {i: caption_rect(e, nodes) for i, e in enumerate(diagram.edges) if e.label}


def crowded_captions(diagram: Diagram) -> list[int]:
    """Indexes of the edges whose caption is within CAPTION_CLEAR of a node, label, title, border, other caption or
    other edge."""
    nodes, frames = leaves(diagram), groups(diagram)
    walls = [*obstacles(nodes), *(title_rect(g) for g in frames)]
    segs = [segments(polyline(e, nodes)) for e in diagram.edges]
    boxes = _boxes(diagram)
    frame_lines = [s for g in frames for s in borders(g)]
    out = []
    for i, b in boxes.items():
        zone = inflate(b, CAPTION_CLEAR)
        lines = (*frame_lines, *(s for j, ss in enumerate(segs) if j != i for s in ss))
        if (any(overlap(zone, r) > 0 for r in (*walls, *(boxes[j] for j in boxes if j != i)))
                or any(crosses(s, zone) for s in lines)):
            out.append(i)
    return out


def _distance(p: Point, seg: Seg) -> float:
    (ax, ay), (bx, by) = seg
    return hypot(p[0] - min(max(p[0], min(ax, bx)), max(ax, bx)), p[1] - min(max(p[1], min(ay, by)), max(ay, by)))


def _caption_problems(diagram: Diagram) -> tuple[int, int, int, int]:
    nodes, frames = leaves(diagram), groups(diagram)
    walls = obstacles(nodes)
    segs = [segments(polyline(e, nodes)) for e in diagram.edges]
    boxes = _boxes(diagram)
    frame_lines = [s for g in frames for s in borders(g)]
    titles = [title_rect(g) for g in frames]
    far = sum(min(_distance(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), s) for s in segs[i]) > (b[3] - b[1]) / 2 + CAPTION_NEAR
              for i, b in boxes.items())
    on_line = sum(any(overlap(b, t) > 0 for t in titles)
                  or any(crosses(s, b) for s in (*frame_lines, *(s for j, ss in enumerate(segs) if j != i for s in ss)))
                  for i, b in boxes.items())
    return (sum(overlap(boxes[a], boxes[b]) > 0 for a, b in combinations(boxes, 2)),
            sum(any(overlap(b, w) > 0 for w in walls) for b in boxes.values()), on_line, far)


def stats(diagram: Diagram) -> RouteStats:
    nodes, frames = leaves(diagram), groups(diagram)
    walls = obstacles(nodes)
    polys = [polyline(e, nodes) for e in diagram.edges]
    segs = [segments(p) for p in polys]
    over, on_node, on_line, far = _caption_problems(diagram)
    return RouteStats(
        edges=len(polys),
        bends=sum(_turns(p) for p in polys),
        crossings=sum(_crosses(a, b) for sa, sb in combinations(segs, 2) for a in sa for b in sb),
        caption_overlaps=over,
        caption_on_node=on_node,
        edge_through_node=sum(any(crosses(s, w) for s in ss for w in walls) for ss in segs),
        caption_on_line=on_line,
        edge_through_group=sum(any(crosses(s, group_rect(g)) for s in ss for g in foreign(frames, nodes[e.src],
                                                                                           nodes[e.dst]))
                               for e, ss in zip(diagram.edges, segs)),
        edge_through_title=sum(any(crosses(s, t) for s in ss for t in map(title_rect, frames)) for ss in segs),
        lines_too_close=sum(g is not None and g < LINE_GAP for sa, sb in combinations(segs, 2)
                            for a in sa for b in sb for g in [parallel_gap(a, b)]),
        line_on_frame=sum(g is not None and g < LINE_GAP for ss in segs for s in ss for f in frames
                          for b in borders(f) for g in [parallel_gap(s, b)]),
        ports_too_close=_ports_too_close(diagram),
        line_near_node=_near_node(diagram),
        caption_crowding=len(crowded_captions(diagram)),
        caption_far=far,
        angled_segments=sum(abs(b[0] - a[0]) > 0.5 and abs(b[1] - a[1]) > 0.5 for p in polys for a, b in pairwise(p)))


def measure(drawio: str) -> RouteStats:
    return stats(read(drawio))
