"""Layout of the group tree: frames (cloud, region, account) wrap blocks, blocks hold child blocks and a node grid."""

import math
from typing import Any

from cartographer.diagram_model import BOX_H, BOX_W, ICON, Box, Group, Icon, has_icon
from cartographer.tf_colors import FRAMES, Colours
from cartographer.tf_geom import NODE_CLEAR, label_size

CELL_W = CELL_H = 150  # icon pitch: ICON plus a label below, with air
GROUP_PAD_X, GROUP_PAD_TOP = 30, 50
FRAME_PAD_X, FRAME_PAD_TOP = 20, 40
GAP = 40
LABEL_CHAR_W, LABEL_PAD = 7, 40
Curated = dict[str, Any]
Size = tuple[int, int]


def empty_blocks(curated: Curated) -> list[str]:
    """Ids of blocks (groups that are not frames) with no nodes of their own and no non-empty child block."""
    parent = {g["id"]: g["parent"] for g in curated["groups"]}
    live: set[str] = set()
    for gid in {n["group"] for n in curated["nodes"]}:
        while gid in parent and gid not in live:
            live.add(gid)
            gid = parent[gid]
    return [g["id"] for g in curated["groups"] if g["kind"] not in FRAMES and g["id"] not in live]


def cell_w(labels: list[str]) -> int:
    """Icon pitch: room for the widest label with NODE_CLEAR either side."""
    return max([CELL_W, *(label_size(t)[0] + 2 * NODE_CLEAR for t in labels)])


def shape(n: dict[str, Any]) -> str:
    """What a node is drawn as: its `icon` (a generic or brand shape for a non-AWS node), else its AWS service."""
    return n.get("icon", n["service"])


def _cell_w(nodes: list[dict[str, Any]]) -> int:
    """Grids holding a plain box widen every cell so neighbouring boxes cannot overlap."""
    if any(not has_icon(shape(n)) for n in nodes):
        return BOX_W + GAP
    return cell_w([_label(n) for n in nodes])


def _grid(nodes: list[dict[str, Any]], cols: int) -> Size:
    """Size of the nodes' cells in at most `cols` columns."""
    return min(len(nodes), cols) * _cell_w(nodes), math.ceil(len(nodes) / cols) * CELL_H


def _label(n: dict[str, Any]) -> str:
    return n["label"] + (" (x N)" if n.get("multi") else "")


class Blocks:
    """Places the group tree with at most `cols` node columns per block; empty blocks are left out."""

    def __init__(self, curated: Curated, cols: int) -> None:
        self.colours = Colours(curated)
        empty = set(empty_blocks(curated))
        self.cols = cols
        self.groups = {g["id"]: g for g in curated["groups"] if g["id"] not in empty}
        self.frames = [g for g, v in self.groups.items() if v["kind"] in FRAMES]
        self.blocks = [g for g, v in self.groups.items() if v["kind"] not in FRAMES]
        self.children = {b: [c for c in self.blocks if self.groups[c]["parent"] == b] for b in self.blocks}
        self.nodes: dict[str | None, list[dict[str, Any]]] = {}
        for n in curated["nodes"]:
            self.nodes.setdefault(n["group"], []).append(n)
        self.out_frames: list[Group] = []
        self.out_groups: list[Group] = []
        self.out_leaves: list[Icon | Box] = []

    def measure(self, bid: str) -> Size:
        kids = [self.measure(c) for c in self.children[bid]]
        own = self.nodes.get(bid, [])
        grid_w, grid_h = _grid(own, self.cols) if own else (0, 0)
        stacked = [h for _, h in kids] + ([grid_h] if own else [])
        label_w = LABEL_CHAR_W * len(self.groups[bid]["label"]) + LABEL_PAD
        return (max(max([grid_w, *(w for w, _ in kids)]) + 2 * GROUP_PAD_X, label_w),
                GROUP_PAD_TOP + sum(stacked) + GAP * (len(stacked) - 1) + GROUP_PAD_X)

    def place_leaves(self, nodes: list[dict[str, Any]], x: int, y: int, parent: str | None, cols: int) -> None:
        cell_w = _cell_w(nodes)
        for i, n in enumerate(nodes):
            cx, cy = x + (i % cols) * cell_w, y + (i // cols) * CELL_H
            if has_icon(shape(n)):
                self.out_leaves.append(Icon(n["id"], _label(n), shape(n), cx + (cell_w - ICON) // 2, cy, parent))
            else:
                self.out_leaves.append(Box(n["id"], _label(n), cx + (cell_w - BOX_W) // 2,
                                           cy + (ICON - BOX_H) // 2, parent=parent))

    def place(self, bid: str, x: int, y: int, w: int) -> int:
        """Place a block at (x, y) with width w; return its height."""
        g = self.groups[bid]
        _, h = self.measure(bid)
        self.out_groups.append(Group(bid, g["label"], x, y, w, h, g["parent"], g["kind"], stroke=self.colours.group(bid)))
        top = y + GROUP_PAD_TOP
        for c in self.children[bid]:
            top += self.place(c, x + GROUP_PAD_X, top, self.measure(c)[0]) + GAP
        self.place_leaves(self.nodes.get(bid, []), x + GROUP_PAD_X, top, bid, self.cols)
        return h

    def _columns(self, x: int, y: int, parent: str | None, tops: list[str], loose: list[dict[str, Any]]) -> Size:
        """Place top-level blocks in column order, then loose nodes in a row underneath; return the size used."""
        cols: dict[int, list[str]] = {}
        for b in tops:
            cols.setdefault(self.groups[b]["column"], []).append(b)
        cx, col_h = x, []
        for _, members in sorted(cols.items()):
            w = max(self.measure(b)[0] for b in members)
            cy = y
            for b in members:
                cy += self.place(b, cx, cy, w) + GAP
            col_h.append(cy - GAP - y)
            cx += w + GAP
        used_w, used_h = max(cx - GAP - x, 0), max(col_h, default=0)
        if loose:
            row_cols = max(used_w // _cell_w(loose), 1)
            self.place_leaves(loose, x, y + used_h + (GAP if used_h else 0), parent, row_cols)
            loose_w, loose_h = _grid(loose, row_cols)
            used_h += (GAP if used_h else 0) + loose_h
            used_w = max(used_w, loose_w)
        return used_w, used_h

    def _frame_chain(self) -> list[str]:
        """Frames from outermost to innermost, following the deepest frame's ancestry."""
        def depth(fid: str) -> int:
            parent = self.groups[fid]["parent"]
            return 1 + (depth(parent) if parent in self.frames else 0)

        chain: list[str] = []
        if self.frames:
            fid: str | None = max(self.frames, key=depth)
            while fid in self.frames:
                chain.insert(0, fid)
                fid = self.groups[fid]["parent"]
        return chain

    def place_frames(self, x: int, y: int) -> Size:
        """Place the frames and everything inside them at (x, y); return the outer size."""
        chain = self._frame_chain()
        n = len(chain)
        # Blocks whose parent is not a block, and nodes not in a block, live directly in the innermost frame.
        tops = [b for b in self.blocks if self.groups[b]["parent"] not in self.children]
        loose = [m for gid, ns in self.nodes.items() if gid not in self.children for m in ns]
        used_w, used_h = self._columns(x + n * FRAME_PAD_X, y + n * FRAME_PAD_TOP, chain[-1] if chain else None,
                                       tops, loose)
        w, h = used_w + 2 * n * FRAME_PAD_X, used_h + n * (FRAME_PAD_TOP + FRAME_PAD_X)
        for depth, fid in enumerate(chain):
            g = self.groups[fid]
            self.out_frames.append(Group(fid, g["label"], x + depth * FRAME_PAD_X, y + depth * FRAME_PAD_TOP,
                                         w - 2 * depth * FRAME_PAD_X, h - depth * (FRAME_PAD_TOP + FRAME_PAD_X),
                                         g["parent"], g["kind"]))
        return w, h
