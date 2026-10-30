"""Plane geometry shared by routing, caption placement and the layout check: clearances, text sizes, obstacles,
ports, polylines."""

import math
from itertools import pairwise

from cartographer.diagram_model import FRAME_TITLE_LEFT, GROUP_TITLE_LEFT, ICON, Box, Diagram, Edge, Group, Icon, Point

GLYPH_W, TEXT_PAD = 7.5, 8
ICON_LINE_H, ICON_LABEL_PAD, CAPTION_LINE_H = 16, 6, 20
LINE_GAP = 12  # parallel segments of different edges, when their extents overlap, keep this far apart
PORT_GAP = 12  # ports on one side of a node
PORT_EDGE = 8  # ports keep this far from the corners of their side
NODE_CLEAR = 10  # a line keeps this far from an icon, its label or a box it does not end at
CAPTION_CLEAR = 6  # a caption keeps this far from everything but its own line
CAPTION_NEAR = 6  # a caption lies at most this far from its own line
GROUP_CLEAR = CAPTION_CLEAR + CAPTION_LINE_H // 2 + 1  # a line keeps this far from a group it does not end in, so a caption fits on it

TITLE_SPACING = 2  # draw.io's default spacing round a group title

Rect = tuple[int, int, int, int]
Seg = tuple[Point, Point]
Size = tuple[int, int]
Leaf = Icon | Box
SIDES = "LRTB"


def _text(text: str) -> tuple[int, int]:
    """(width, line count) of text drawn at GLYPH_W per character, without wrapping."""
    lines = text.split("\n")
    return math.ceil(max(map(len, lines)) * GLYPH_W + TEXT_PAD), len(lines)


def label_size(text: str) -> Size:
    """Size of the label under an icon."""
    w, n = _text(text)
    return w, n * ICON_LINE_H + ICON_LABEL_PAD


def caption_size(text: str) -> Size:
    """Size of an arrow caption; none for no text."""
    if not text:
        return 0, 0
    w, n = _text(text)
    return w, n * CAPTION_LINE_H


def inflate(rect: Rect, margin: int) -> Rect:
    return rect[0] - margin, rect[1] - margin, rect[2] + margin, rect[3] + margin


def leaves(diagram: Diagram) -> dict[str, Leaf]:
    return {n.id: n for n in diagram.nodes if not isinstance(n, Group)}


def groups(diagram: Diagram) -> list[Group]:
    return [n for n in diagram.nodes if isinstance(n, Group)]


def group_rect(group: Group, margin: int = 0) -> Rect:
    return group.x - margin, group.y - margin, group.x + group.w + margin, group.y + group.h + margin


def foreign(all_groups: list[Group], *ends: Leaf) -> list[Group]:
    """The groups that contain none of the given nodes: the ones an edge between them must stay out of."""
    shapes = [body(n) for n in ends]
    return [g for g in all_groups
            if not any(g.x <= x0 and g.y <= y0 and x1 <= g.x + g.w and y1 <= g.y + g.h for x0, y0, x1, y1 in shapes)]


def borders(group: Group) -> list[Seg]:
    x0, y0, x1, y1 = group_rect(group)
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


def title_rect(group: Group) -> Rect:
    """The band a group's title takes at its top-left, every line of it, the frame icon included."""
    w, n = _text(group.label)
    left = FRAME_TITLE_LEFT if group.kind else GROUP_TITLE_LEFT
    return group.x, group.y, group.x + left + w, group.y + 2 * TITLE_SPACING + n * ICON_LINE_H


def body(node: Leaf) -> Rect:
    """The connectable shape: the 60 px icon, or the box."""
    w, h = (ICON, ICON) if isinstance(node, Icon) else (node.w, node.h)
    return node.x, node.y, node.x + w, node.y + h


def label_rect(node: Icon) -> Rect:
    """The label zone under an icon, centred on it."""
    x0, _, x1, y1 = body(node)
    w, h = label_size(node.label)
    cx = (x0 + x1) // 2
    return cx - w // 2, y1, cx - w // 2 + w, y1 + h


def rects(node: Leaf, margin: int = 0) -> list[Rect]:
    """Everything a leaf occupies, inflated by `margin`: the shape and, for an icon, the label under it."""
    out = [inflate(body(node), margin)]
    if isinstance(node, Icon):
        out.append(inflate(label_rect(node), margin))
    return out


def obstacles(nodes: dict[str, Leaf], margin: int = 0) -> list[Rect]:
    return [r for n in nodes.values() for r in rects(n, margin)]


def side_size(node: Leaf, side: str) -> int:
    """Length of the side ports sit on; an icon's bottom side is as wide as its label."""
    x0, y0, x1, y1 = body(node)
    if side in "LR":
        return y1 - y0
    return max(x1 - x0, label_size(node.label)[0]) if isinstance(node, Icon) and side == "B" else x1 - x0


def capacity(node: Leaf, side: str) -> int:
    """How many ports fit on a side at PORT_GAP, PORT_EDGE from the corners."""
    return (side_size(node, side) - 2 * PORT_EDGE) // PORT_GAP + 1


def side_of(port: tuple[float, float]) -> str:
    fx, fy = port
    return "L" if fx == 0 else "R" if fx == 1 else "T" if fy == 0 else "B"


def port_xy(node: Leaf, port: tuple[float, float] | None, off: Point = (0, 0)) -> Point:
    x0, y0, x1, y1 = body(node)
    fx, fy = port or (0.5, 0.5)
    return round(x0 + fx * (x1 - x0)) + off[0], round(y0 + fy * (y1 - y0)) + off[1]


def polyline(edge: Edge, nodes: dict[str, Leaf]) -> list[Point]:
    return [port_xy(nodes[edge.src], edge.out, edge.out_off), *edge.points,
            port_xy(nodes[edge.dst], edge.into, edge.into_off)]


def segments(poly: list[Point]) -> list[Seg]:
    return list(pairwise(poly))


def length(seg: Seg) -> int:
    (ax, ay), (bx, by) = seg
    return abs(bx - ax) + abs(by - ay)


def point_at(poly: list[Point], at: float) -> Point:
    """Where draw.io puts a label with relative position `at` (-1 source end, 1 target end): mxGraphView.getPoint."""
    lens = [length(s) for s in segments(poly)]
    dist = round((at / 2 + 0.5) * sum(lens))
    done, i = 0, 0
    while i < len(lens) - 1 and dist >= round(done + lens[i]):
        done += lens[i]
        i += 1
    (ax, ay), (bx, by) = poly[i], poly[i + 1]
    f = (dist - done) / lens[i] if lens[i] else 0
    return ax + (bx - ax) * f, ay + (by - ay) * f


def overlap(a: Rect, b: Rect) -> int:
    """Area shared by two rectangles; touching edges share none."""
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def crosses(seg: Seg, rect: Rect) -> bool:
    """Whether an axis-aligned segment passes through the open interior of the rectangle."""
    (ax, ay), (bx, by) = seg
    x0, x1, y0, y1 = min(ax, bx), max(ax, bx), min(ay, by), max(ay, by)
    return x1 > rect[0] and x0 < rect[2] and y1 > rect[1] and y0 < rect[3]


def parallel_gap(a: Seg, b: Seg) -> int | None:
    """Distance between two parallel segments whose extents overlap along a stretch of positive length."""
    for axis in (0, 1):
        other = 1 - axis
        if a[0][axis] == a[1][axis] and b[0][axis] == b[1][axis]:
            lo = max(min(a[0][other], a[1][other]), min(b[0][other], b[1][other]))
            hi = min(max(a[0][other], a[1][other]), max(b[0][other], b[1][other]))
            return abs(a[0][axis] - b[0][axis]) if hi > lo else None
    return None
