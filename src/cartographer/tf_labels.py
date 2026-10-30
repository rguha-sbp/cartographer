"""Caption placement: each caption sits on its own route, or at most CAPTION_NEAR beside it, and keeps CAPTION_CLEAR
from nodes and their labels, group titles and borders, other captions and other edges."""

from collections.abc import Callable

from cartographer.diagram_model import Edge, Group, Point
from cartographer.tf_geom import (
    CAPTION_CLEAR,
    Leaf,
    Rect,
    Seg,
    borders,
    caption_size,
    crosses,
    inflate,
    length,
    obstacles,
    overlap,
    point_at,
    polyline,
    segments,
    title_rect,
)

STEP = 3  # spacing of candidate positions along a segment
BESIDE = (1, 3, 5)  # distances from the line at which a caption on a horizontal run may sit beside it
SLACK = 1  # the drawn position is rounded to the pixel; clear by this much more than the rule asks
CLEAR = (0, 0, 0)  # the cost of a caption box that touches nothing


def caption_box(text: str, centre: Point) -> Rect:
    w, h = caption_size(text)
    return centre[0] - w // 2, centre[1] - h // 2, centre[0] + (w + 1) // 2, centre[1] + (h + 1) // 2


def caption_rect(edge: Edge, nodes: dict[str, Leaf]) -> Rect:
    x, y = point_at(polyline(edge, nodes), edge.at)
    return caption_box(edge.label, (round(x) + edge.shift[0], round(y) + edge.shift[1]))


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _candidates(text: str, poly: list[Point]) -> list[tuple[Point, Point]]:
    """(route point, shift) pairs, nearest the source first; segments the text fits along come before the rest, and
    on each point the caption sits on the line before it moves to either side of it."""
    w, h = caption_size(text)
    fits, rest = [], []
    for (ax, ay), (bx, by) in segments(poly):
        n = abs(bx - ax) + abs(by - ay)
        horizontal = ay == by
        half = (w if horizontal else h) // 2
        ts = range(half, n - half + 1, STEP) if n >= 2 * half else [n // 2]
        shifts = [(0, 0), *((0, s * (h // 2 + d)) for d in BESIDE for s in (1, -1))] if horizontal else [(0, 0)]
        for t in ts:
            p = (ax + _sign(bx - ax) * t, ay + _sign(by - ay) * t)
            (fits if n >= 2 * half else rest).extend((p, shift) for shift in shifts)
    return fits + rest


class Captions:
    """Places captions one edge at a time as the edges are routed. Each is clear of the nodes, titles and borders,
    of the captions placed before it, and of every other edge: the routes so far and the ports' stubs. Once every
    route is known, a caption no longer `clear` is placed again, off the routes drawn after it."""

    def __init__(self, nodes: dict[str, Leaf], frames: list[Group], stubs: list[list[Seg]]) -> None:
        self.walls = [*obstacles(nodes), *map(title_rect, frames)]
        self.lines = [(i, s) for i, segs in enumerate(stubs) for s in segs] + [(-1, s) for g in frames for s in borders(g)]
        self.taken: dict[int, Rect] = {}

    def add_route(self, i: int, poly: list[Point]) -> None:
        self.lines += [(i, s) for s in segments(poly)]

    def _scorer(self, i: int, near: Rect) -> Callable[[Rect], tuple[int, int, int]]:
        """Cost of a box inside `near` for edge i's caption: (nodes, titles, other captions and lines it overlaps,
        things in its clearance, its overlap area with nodes and titles)."""
        walls = [r for r in self.walls if overlap(near, r) > 0]
        solid = [*walls, *(r for j, r in self.taken.items() if j != i and overlap(near, r) > 0)]
        lines = [s for j, s in self.lines if j != i and crosses(s, near)]

        def cost(box: Rect) -> tuple[int, int, int]:
            zone = inflate(box, CAPTION_CLEAR + SLACK)
            return (sum(overlap(box, r) > 0 for r in solid) + sum(crosses(s, box) for s in lines),
                    sum(overlap(zone, r) > 0 for r in solid) + sum(crosses(s, zone) for s in lines),
                    sum(overlap(box, r) for r in walls))
        return cost

    def clear(self, i: int) -> bool:
        """Whether edge i's caption is still clear of everything placed and routed since."""
        zone = inflate(self.taken[i], CAPTION_CLEAR + SLACK)
        return self._scorer(i, zone)(self.taken[i]) == CLEAR

    def place(self, i: int, poly: list[Point], text: str) -> tuple[float, Point, Rect | None]:
        """(`Edge.at`, `Edge.shift`, the zone the caption needs kept free or None when it could not be placed clear)."""
        total = sum(map(length, segments(poly)))
        best: tuple[tuple[int, int, int], Point, Point] | None = None
        w, h = caption_size(text)
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        reach = max(w, 2 * h + max(BESIDE)) + CAPTION_CLEAR + SLACK
        score = self._scorer(i, (min(xs) - reach, min(ys) - reach, max(xs) + reach, max(ys) + reach))
        for p, shift in _candidates(text, poly):
            cost = score(caption_box(text, (p[0] + shift[0], p[1] + shift[1])))
            if best is None or cost < best[0]:
                best = cost, p, shift
            if cost == CLEAR:
                break
        cost, centre, shift = best
        box = caption_box(text, (centre[0] + shift[0], centre[1] + shift[1]))
        self.taken[i] = box
        at = round(2 * _along(poly, centre) / total - 1, 4) if total else 0
        return at, shift, inflate(box, CAPTION_CLEAR + SLACK) if cost == CLEAR else None


def _along(poly: list[Point], p: Point) -> int:
    """Distance from the route's start to a point that lies on it."""
    run = 0
    for seg in segments(poly):
        (ax, ay), (bx, by) = seg
        if min(ax, bx) <= p[0] <= max(ax, bx) and min(ay, by) <= p[1] <= max(ay, by):
            return run + abs(p[0] - ax) + abs(p[1] - ay)
        run += length(seg)
    return run
