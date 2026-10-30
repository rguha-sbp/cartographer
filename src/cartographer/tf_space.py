"""Make room: where a gap between obstacles is too narrow for the lines routed through it, widen that gap.

Demand is measured on a routed diagram: in each channel (the free stretch between the obstacles either side of a
segment) the most segments that run side by side need LINE_GAP apiece plus NODE_CLEAR at both walls. A short channel
is widened by cutting the drawing across it and moving everything beyond the cut; the diagram is then routed again.
"""

from dataclasses import dataclass, replace
from itertools import pairwise

from cartographer.diagram_model import Box, Diagram, Group, Icon
from cartographer.tf_check import crowded_captions, stats
from cartographer.tf_geom import (
    CAPTION_CLEAR,
    CAPTION_LINE_H,
    GROUP_CLEAR,
    LINE_GAP,
    Rect,
    caption_size,
    foreign,
    group_rect,
    groups,
    inflate,
    leaves,
    polyline,
    rects,
    segments,
)
from cartographer.tf_labels import SLACK, STEP, caption_rect
from cartographer.tf_route import route

ROUNDS = 3


@dataclass(frozen=True)
class Widening:
    axis: int  # 0 widens a gap between columns, 1 a gap between rows
    at: int  # coordinate of the cut
    extra: int
    between: tuple[int, int]  # the walls either side of the gap, before widening

    def __str__(self) -> str:
        return f"{'x' if self.axis == 0 else 'y'} {self.between[0]}..{self.between[1]} +{self.extra}"


def _peak(spans: list[tuple[int, int]]) -> int:
    """Most spans that share a stretch of positive length."""
    marks = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans], key=lambda m: (m[0], m[1]))
    level = peak = 0
    for _, step in marks:
        level += step
        peak = max(peak, level)
    return peak


def _extent(r: Rect, axis: int) -> tuple[int, int, int, int]:
    """(near, far) of a wall across `axis` and (start, end) of it along the other axis."""
    return (r[0], r[2], r[1], r[3]) if axis == 0 else (r[1], r[3], r[0], r[2])


def _channels(diagram: Diagram) -> dict[tuple[int, int, int], list[tuple[int, int]]]:
    """(axis, wall before, wall after) -> the spans along the channel of every middle segment running down it."""
    nodes, frames = leaves(diagram), groups(diagram)
    leaf_rects = [r for n in nodes.values() for r in rects(n)]
    out: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    for e in diagram.edges:
        walls = leaf_rects + [group_rect(g) for g in foreign(frames, nodes[e.src], nodes[e.dst])]
        for (ax, ay), (bx, by) in segments(polyline(e, nodes))[1:-1]:
            axis, pos, span = (0, ax, (min(ay, by), max(ay, by))) if ax == bx else (1, ay, (min(ax, bx), max(ax, bx)))
            beside = [_extent(r, axis) for r in walls]
            beside = [w for w in beside if w[2] < span[1] and w[3] > span[0]]
            before = max((w[1] for w in beside if w[1] <= pos), default=None)
            after = min((w[0] for w in beside if w[0] >= pos), default=None)
            if before is not None and after is not None:
                out.setdefault((axis, before, after), []).append(span)
    return out


def _merged(cuts: list[Widening]) -> list[Widening]:
    """Overlapping gaps are widened once, by the most."""
    out: list[Widening] = []
    for w in sorted((w for w in cuts if w.extra > 0), key=lambda w: (w.axis, w.between)):
        if out and out[-1].axis == w.axis and w.between[0] < out[-1].between[1]:
            out[-1] = max(out[-1], w, key=lambda c: c.extra)
        else:
            out.append(w)
    return out


def _channel_widenings(diagram: Diagram) -> list[Widening]:
    return [Widening(axis, (before + after) // 2, _peak(spans) * LINE_GAP + 2 * GROUP_CLEAR - (after - before),
                     (before, after)) for (axis, before, after), spans in sorted(_channels(diagram).items())]


Wall = tuple[int, int, int, int]  # (owner edge or -1, position, start, end)


def _walls(diagram: Diagram) -> tuple[list[Wall], list[Wall]]:
    """(vertical, horizontal) walls that cut a line: group borders, node shapes and labels, every edge's segments,
    and every caption, grown by the room a caption beside it needs."""
    nodes = leaves(diagram)
    fixed = [group_rect(g) for g in groups(diagram)] + [r for n in nodes.values() for r in rects(n)]
    vertical = [(-1, x, r[1], r[3]) for r in fixed for x in (r[0], r[2])]
    horizontal = [(-1, y, r[0], r[2]) for r in fixed for y in (r[1], r[3])]
    for i, e in enumerate(diagram.edges):
        if e.label:
            x0, y0, x1, y1 = inflate(caption_rect(e, nodes), CAPTION_CLEAR + CAPTION_LINE_H // 2)
            vertical += [(i, x0, y0, y1), (i, x1, y0, y1)]
            horizontal += [(i, y0, x0, x1), (i, y1, x0, x1)]
    for i, e in enumerate(diagram.edges):
        for (ax, ay), (bx, by) in segments(polyline(e, nodes)):
            if ax == bx:
                vertical.append((i, ax, min(ay, by), max(ay, by)))
            else:
                horizontal.append((i, ay, min(ax, bx), max(ax, bx)))
    return vertical, horizontal


def _room(walls: list[Wall], i: int, line: int, lo: int, hi: int) -> list[tuple[int, int]]:
    """The free runs along a line between lo and hi: cut by every wall but edge i's that crosses it there."""
    stops = sorted({lo, hi, *(p for o, p, a, b in walls if o != i and a < line < b and lo < p < hi)})
    return list(pairwise(stops))


def _across(walls: list[Wall], i: int, line: int, lo: int, hi: int) -> tuple[int, int] | None:
    """The nearest walls but edge i's either side of a line, parallel to it along some of lo..hi."""
    beside = [p for o, p, a, b in walls if o != i and p != line and a < hi and b > lo]
    before = max((p for p in beside if p < line), default=None)
    after = min((p for p in beside if p > line), default=None)
    return None if before is None or after is None else (before, after)


def _caption_widenings(diagram: Diagram, crowded: list[int]) -> list[Widening]:
    """For each crowded caption, the cheapest of its segments to make room on: the free run along it as long as the
    caption, and the gap across it as wide."""
    nodes = leaves(diagram)
    vertical, horizontal = _walls(diagram)
    margin = 2 * (CAPTION_CLEAR + SLACK + STEP)
    out: list[Widening] = []
    for i in crowded:
        w, h = caption_size(diagram.edges[i].label)
        best: list[Widening] | None = None
        route_segs = segments(polyline(diagram.edges[i], nodes))
        for (ax, ay), (bx, by) in route_segs[1:-1] or route_segs:
            along = ay == by
            line, lo, hi = (ay, min(ax, bx), max(ax, bx)) if along else (ax, min(ay, by), max(ay, by))
            cuts, across = (vertical, horizontal) if along else (horizontal, vertical)
            a, b = max(_room(cuts, i, line, lo, hi), key=lambda r: r[1] - r[0])
            need = [Widening(0 if along else 1, (a + b) // 2, (w if along else h) + margin - (b - a), (a, b))]
            gap = _across(across, i, line, lo, hi)
            if gap:
                need.append(Widening(1 if along else 0, sum(gap) // 2, (h if along else w) + margin - (gap[1] - gap[0]),
                                     gap))
            need = [c for c in need if c.extra > 0]
            if best is None or sum(c.extra for c in need) < sum(c.extra for c in best):
                best = need
        out += best or []
    return out


def widenings(diagram: Diagram) -> list[Widening]:
    """The gaps too narrow for the lines routed through them and for the captions that found no clear spot."""
    return _merged(_channel_widenings(diagram) + _caption_widenings(diagram, crowded_captions(diagram)))


def _shift(n: Group | Icon | Box, axis: int, at: int, extra: int) -> Group | Icon | Box:
    lo, size = (n.x, n.w if not isinstance(n, Icon) else 60) if axis == 0 else (n.y, n.h if not isinstance(n, Icon) else 60)
    if isinstance(n, Group):
        if lo >= at:
            return replace(n, **{"x" if axis == 0 else "y": lo + extra})
        return replace(n, **{"w" if axis == 0 else "h": size + extra}) if lo + size > at else n
    return replace(n, **{"x" if axis == 0 else "y": lo + extra}) if lo + size / 2 >= at else n


def stretch(diagram: Diagram, cuts: list[Widening]) -> Diagram:
    """Move everything beyond each cut by its extra and grow the groups that span it; later cuts first, so no cut
    moves another."""
    for w in sorted(cuts, key=lambda c: (c.axis, -c.at)):
        legend = diagram.legend
        if w.axis == 1 and legend.y >= w.at:
            legend = replace(legend, y=legend.y + w.extra)
        diagram = replace(diagram, nodes=tuple(_shift(n, w.axis, w.at, w.extra) for n in diagram.nodes), legend=legend)
    return diagram


def fit(diagram: Diagram) -> tuple[Diagram, list[Widening]]:
    """Route the diagram, widening short gaps and routing again (at most ROUNDS times) until nothing is violated."""
    done: list[Widening] = []
    routed = route(diagram)
    for _ in range(ROUNDS):
        cuts = widenings(routed) if stats(routed).violations else []
        if not cuts:
            break
        routed = route(stretch(routed, cuts))
        done += cuts
    return routed, done
