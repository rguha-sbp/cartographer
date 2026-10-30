"""The routing grid: candidate lines, the walls on them, and the least-cost search over them.

A grid segment within LINE_GAP of a parallel segment another edge already uses is closed to later edges (`hard`),
or only dear when no clean route exists. A segment through a placed caption's zone is dear like a crossing, so a
route goes round a caption when the detour is short and through it (to be placed again) when it is not. A segment within LINE_GAP of a parallel group border is closed too: lines
cross a frame at a right angle and run along it only when nothing else is left.
"""

from bisect import bisect_left, bisect_right
from heapq import heappop, heappush
from itertools import pairwise

from cartographer.diagram_model import Point
from cartographer.tf_geom import LINE_GAP, Rect

OUTER = 40  # free lines kept round the whole drawing
CLEAR = 4  # closest two candidate lines may be
MAX_TRACKS = 14  # most tracks laid in one gap
BEND, OVERLAP, SHARED, CROSS = 40, 40, 400, 300
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))  # east, west, south, north
REVERSE = (1, 0, 3, 2)
MIXED = -1  # owner of a segment that two edges close


def _lines(required: set[int], optional: set[int]) -> list[int]:
    """Candidate lines on one axis: every required one, the optional ones that keep CLEAR from the others, and
    tracks LINE_GAP apart inside each wide gap."""
    kept = sorted(required)

    def add(v: int) -> None:
        i = bisect_left(kept, v)
        if all(abs(v - kept[j]) >= CLEAR for j in (i - 1, i) if 0 <= j < len(kept)):
            kept.insert(i, v)

    for v in sorted(optional):
        add(v)
    for a, b in pairwise(kept[:]):
        n = min(MAX_TRACKS, (b - a) // LINE_GAP)
        pitch = (b - a) / (n + 1) if n == MAX_TRACKS else LINE_GAP
        for k in range(1, n + 1):
            add(a + round(pitch * k))
    return kept


def _close(lines: list[int]) -> list[list[int]]:
    """For each line, the indexes of the lines closer than LINE_GAP, itself included."""
    return [[j for j, w in enumerate(lines) if abs(w - v) < LINE_GAP] for v in lines]


Mask = list[bytearray]  # [horizontal by row, vertical by column]; 1 where a grid segment would pass through a wall


class Grid:
    def __init__(self, walls: list[Rect], groups: list[Rect], frames: list[Rect], stubs: list[Point]) -> None:
        every = walls + groups
        self.xs = _lines({p[0] for p in stubs}, {v for r in every for v in (r[0], r[2])}
                         | {min(r[0] for r in every) - OUTER, max(r[2] for r in every) + OUTER})
        self.ys = _lines({p[1] for p in stubs}, {v for r in every for v in (r[1], r[3])}
                         | {min(r[1] for r in every) - OUTER, max(r[3] for r in every) + OUTER})
        nx, ny = len(self.xs), len(self.ys)
        self.xi = {x: i for i, x in enumerate(self.xs)}
        self.yi = {y: i for i, y in enumerate(self.ys)}
        self.owner = [[0] * (nx * ny), [0] * (nx * ny)]  # edge number + 1 that closes the segment, or MIXED
        self.close = (_close(self.ys), _close(self.xs))  # by axis: lines a segment of that axis closes
        self.through = [bytearray(nx * ny), bytearray(nx * ny)]  # an earlier edge runs straight through the vertex
        self.walls = self._mask(walls)
        self.beside = self._beside(frames)
        self.group_masks = [self._mask([g]) for g in groups]
        self.captions: Mask = [bytearray(nx * ny), bytearray(nx * ny)]

    def _mask(self, rects: list[Rect]) -> Mask:
        nx, ny = len(self.xs), len(self.ys)
        mask = [bytearray(nx * ny), bytearray(nx * ny)]
        for x0, y0, x1, y1 in rects:
            rows = range(bisect_right(self.ys, y0), bisect_left(self.ys, y1))
            cols = range(max(bisect_right(self.xs, x0) - 1, 0), bisect_left(self.xs, x1))
            for iy in rows:
                for ix in cols:
                    mask[0][iy * nx + ix] = 1
            for ix in range(bisect_right(self.xs, x0), bisect_left(self.xs, x1)):
                for iy in range(max(bisect_right(self.ys, y0) - 1, 0), bisect_left(self.ys, y1)):
                    mask[1][ix * ny + iy] = 1
        return mask

    def _beside(self, frames: list[Rect]) -> Mask:
        """The grid segments that run parallel to a frame border, closer than LINE_GAP, along a stretch of it."""
        nx, ny = len(self.xs), len(self.ys)
        mask = [bytearray(nx * ny), bytearray(nx * ny)]
        for x0, y0, x1, y1 in frames:
            for axis, lines, across, (lo, hi), size, step in ((0, self.ys, self.xs, (x0, x1), nx, (y0, y1)),
                                                             (1, self.xs, self.ys, (y0, y1), ny, (x0, x1))):
                near = {i for border in step for i in range(bisect_right(lines, border - LINE_GAP),
                                                              bisect_left(lines, border + LINE_GAP))}
                along = range(max(bisect_right(across, lo) - 1, 0), bisect_left(across, hi))
                for i in near:
                    for k in along:
                        mask[axis][i * size + k] = 1
        return mask

    @staticmethod
    def _merge(into: Mask, extra: Mask) -> Mask:
        return [bytearray((int.from_bytes(a) | int.from_bytes(b)).to_bytes(len(a))) for a, b in zip(into, extra)]

    def add_caption(self, zone: Rect) -> None:
        """Make the space a placed caption needs dear, for the edges routed after it."""
        self.captions = self._merge(self.captions, self._mask([zone]))

    def blocked(self, groups: list[int], beside: bool = True) -> Mask:
        """The leaf walls, the strips along frame borders and the walls of the chosen groups (indexes into the
        `groups` given)."""
        out = self._merge(self.walls, self.beside) if beside else [bytearray(m) for m in self.walls]
        for g in groups:
            out = self._merge(out, self.group_masks[g])
        return out

    def _slot(self, ix: int, iy: int, d: int) -> tuple[int, int]:
        """(axis, index) of the grid segment leaving vertex (ix, iy) in direction d."""
        if d < 2:
            return 0, iy * len(self.xs) + min(ix, ix + DIRS[d][0])
        return 1, ix * len(self.ys) + min(iy, iy + DIRS[d][1])

    def route(self, start: Point, first: int, goal: Point, blocked: Mask, edge: int,
              hard: bool = True) -> list[tuple[int, int]] | None:
        nx, ny = len(self.xs), len(self.ys)
        gx, gy = self.xi[goal[0]], self.yi[goal[1]]
        sx, sy = self.xi[start[0]], self.yi[start[1]]
        begin = (sx * ny + sy) * 4 + first
        best, prev = {begin: 0}, {}
        heap = [(0, 0, begin)]
        while heap:
            _, g, s = heappop(heap)
            if g > best[s]:
                continue
            v, heading = divmod(s, 4)
            ix, iy = divmod(v, ny)
            if (ix, iy) == (gx, gy):
                path = [(ix, iy)]
                while s != begin:
                    s = prev[s]
                    path.append(divmod(s // 4, ny))
                return path[::-1]
            for d in range(4):
                nix, niy = ix + DIRS[d][0], iy + DIRS[d][1]
                if d == REVERSE[heading] or not (0 <= nix < nx and 0 <= niy < ny):
                    continue
                axis, k = self._slot(ix, iy, d)
                if blocked[axis][k]:
                    continue
                step = abs(self.xs[nix] - self.xs[ix]) + abs(self.ys[niy] - self.ys[iy])
                taken = self.owner[axis][k] not in (0, edge + 1)
                if taken and hard:
                    continue
                cost = step + (step * OVERLAP + SHARED) * taken + CROSS * self.captions[axis][k]
                if d != heading:
                    cost += BEND
                elif self.through[1 - axis][ix * ny + iy]:
                    cost += CROSS
                ns, ng = (nix * ny + niy) * 4 + d, g + cost
                if ng < best.get(ns, 1 << 60):
                    best[ns], prev[ns] = ng, s
                    heappush(heap, (ng + abs(self.xs[nix] - self.xs[gx]) + abs(self.ys[niy] - self.ys[gy]), ng, ns))
        return None

    def _close_off(self, axis: int, line: int, first: int, last: int, edge: int) -> None:
        """Close the grid segments first..last-1 along a line, and the parallel ones nearer than LINE_GAP."""
        size = len(self.xs) if axis == 0 else len(self.ys)
        for other in self.close[axis][line]:
            base = other * size
            for k in range(base + first, base + last):
                self.owner[axis][k] = edge + 1 if self.owner[axis][k] in (0, edge + 1) else MIXED

    def reserve(self, a: Point, b: Point, edge: int) -> None:
        """Close the grid segments between a port and its stub end `b` to every other edge, and the line across the
        stub end, LINE_GAP either side of it, to every edge: a route leaves its stub straight on, and no route runs
        over a stub end, where it would box that stub in or jog beside it."""
        across = 1 if a[1] == b[1] else 0  # axis of the segments that cross the stub's line
        lines, at = (self.ys, b[1]) if across else (self.xs, b[0])
        line = self.xi[b[0]] if across else self.yi[b[1]]
        size = len(self.ys) if across else len(self.xs)
        for k in range(max(bisect_right(lines, at - LINE_GAP) - 1, 0), bisect_left(lines, at + LINE_GAP)):
            self.owner[across][line * size + k] = MIXED
        (x0, y0), (x1, y1) = sorted((a, b))
        if y0 == y1:
            first, last = bisect_left(self.xs, x0), bisect_right(self.xs, x1) - 1
            self._close_off(0, self.yi[y0], first, last, edge)
            for ix in range(first + 1, last):
                self.through[0][ix * len(self.ys) + self.yi[y0]] = 1
        else:
            first, last = bisect_left(self.ys, y0), bisect_right(self.ys, y1) - 1
            self._close_off(1, self.xi[x0], first, last, edge)
            for iy in range(first + 1, last):
                self.through[1][self.xi[x0] * len(self.ys) + iy] = 1

    def commit(self, path: list[tuple[int, int]], edge: int) -> None:
        ny = len(self.ys)
        for i, ((ax, ay), (bx, by)) in enumerate(pairwise(path)):
            if ay == by:
                self._close_off(0, ay, min(ax, bx), max(ax, bx), edge)
            else:
                self._close_off(1, ax, min(ay, by), max(ay, by), edge)
            if i and (ax - path[i - 1][0], ay - path[i - 1][1]) == (bx - ax, by - ay):
                self.through[0 if ay == by else 1][ax * ny + ay] = 1


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)
