"""Layout of the group tree: frames (cloud, region, account) wrap blocks, blocks hold child blocks and a node grid."""

import math
from typing import Any

from cartographer import icons
from cartographer.diagram_model import BOX_H, BOX_W, GREY, ICON, Box, Group, Icon
from cartographer.tf_colors import FRAMES, Colours
from cartographer.tf_geom import GROUP_CLEAR, LINE_GAP, NODE_CLEAR, label_size

CELL_W = CELL_H = 150  # icon pitch: ICON plus a label below, with air
GROUP_PAD_X, GROUP_PAD_TOP = 30, 50
FRAME_PAD_X, FRAME_PAD_TOP = 20, 40
GAP = 40  # air beside a box; a notation sets the air below it (its row_gap)
CHANNEL_TRACKS = 6  # lines that fit between two blocks side by side, each keeping GROUP_CLEAR from both
BLOCK_GAP = 2 * GROUP_CLEAR + (CHANNEL_TRACKS - 1) * LINE_GAP
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
    """What a node is drawn as: its `icon`, a qualified icon name or, for a plain box, the shape its notation draws."""
    return n.get("icon", "none")


def box_size(n: dict[str, Any]) -> Size:
    """A plain box's size: its curated `box`, else the default box."""
    w, h = n.get("box", (BOX_W, BOX_H))
    return w, h


def group_label(g: dict[str, Any]) -> str:
    """A group's title: a VPC also names its address ranges and, when this stack does not create it, `external`."""
    notes = list(g.get("cidrs") or [])
    if g.get("external"):
        notes.append("External")
    return f"{g['label']} ({', '.join(notes)})" if notes else g["label"]


def _label(n: dict[str, Any]) -> str:
    return n["label"] + (" (x N)" if n.get("multi") else "")


class Blocks:
    """Places the group tree with at most `cols` node columns per block and `row_gap` between whatever stacks
    vertically in a block; empty blocks are left out."""

    def __init__(self, curated: Curated, cols: int, row_gap: int) -> None:
        self.colours = Colours(curated)
        empty = set(empty_blocks(curated))
        self.cols, self.row_gap = cols, row_gap
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

    def _cell(self, nodes: list[dict[str, Any]]) -> Size:
        """Grids holding a plain box widen every cell to the widest box so neighbouring boxes cannot overlap, and
        heighten it to the tallest box with row_gap below."""
        boxes = [box_size(n) for n in nodes if not icons.known(shape(n))]
        if not boxes:
            return cell_w([_label(n) for n in nodes]), CELL_H
        return max(w for w, _ in boxes) + GAP, max(CELL_H, max(h for _, h in boxes) + self.row_gap)

    def _grid(self, nodes: list[dict[str, Any]], cols: int) -> Size:
        """Size of the nodes' cells in at most `cols` columns."""
        w, h = self._cell(nodes)
        return min(len(nodes), cols) * w, math.ceil(len(nodes) / cols) * h

    def measure(self, bid: str) -> Size:
        kids = [self.measure(c) for c in self.children[bid]]
        own = self.nodes.get(bid, [])
        grid_w, grid_h = self._grid(own, self.cols) if own else (0, 0)
        stacked = [h for _, h in kids] + ([grid_h] if own else [])
        label_w = LABEL_CHAR_W * len(group_label(self.groups[bid])) + LABEL_PAD
        return (max(max([grid_w, *(w for w, _ in kids)]) + 2 * GROUP_PAD_X, label_w),
                GROUP_PAD_TOP + sum(stacked) + self.row_gap * (len(stacked) - 1) + GROUP_PAD_X)

    def place_leaves(self, nodes: list[dict[str, Any]], x: int, y: int, parent: str | None, cols: int) -> None:
        cw, ch = self._cell(nodes)
        for i, n in enumerate(nodes):
            cx, cy = x + (i % cols) * cw, y + (i // cols) * ch
            if icons.known(shape(n)):
                self.out_leaves.append(Icon(n["id"], _label(n), shape(n), cx + (cw - ICON) // 2, cy, parent))
            else:
                w, h = box_size(n)  # level with an icon's middle; a box taller than an icon starts at the cell top
                self.out_leaves.append(Box(n["id"], _label(n), cx + (cw - w) // 2, cy + max(ICON - h, 0) // 2, w, h,
                                           parent, shape(n)))

    def place(self, bid: str, x: int, y: int, w: int) -> int:
        """Place a block at (x, y) with width w; return its height."""
        g = self.groups[bid]
        _, h = self.measure(bid)
        self.out_groups.append(Group(bid, group_label(g), x, y, w, h, g["parent"], g["kind"], g.get("tier"),
                                     stroke=self.colours.group(bid) or GREY, cloud=g.get("cloud")))
        top = y + GROUP_PAD_TOP
        for c in self.children[bid]:
            top += self.place(c, x + GROUP_PAD_X, top, self.measure(c)[0]) + self.row_gap
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
                cy += self.place(b, cx, cy, w) + BLOCK_GAP
            col_h.append(cy - BLOCK_GAP - y)
            cx += w + BLOCK_GAP
        used_w, used_h = max(cx - BLOCK_GAP - x, 0), max(col_h, default=0)
        if loose:
            row_cols = max(used_w // self._cell(loose)[0], 1)
            above = self.row_gap if used_h else 0
            self.place_leaves(loose, x, y + used_h + above, parent, row_cols)
            loose_w, loose_h = self._grid(loose, row_cols)
            used_h += above + loose_h
            used_w = max(used_w, loose_w)
        return used_w, used_h

    def _frame_tree(self) -> tuple[list[str], dict[str, list[str]]]:
        """Root frames and each frame's child frames, in order of first appearance in the curated groups."""
        kids = {f: [c for c in self.frames if self.groups[c]["parent"] == f] for f in self.frames}
        return [f for f in self.frames if self.groups[f]["parent"] not in kids], kids

    def place_frames(self, x: int, y: int) -> Size:
        """Place the frame trees side by side and everything inside them at (x, y); return the outer size."""
        roots, kids = self._frame_tree()
        # Blocks whose parent is not a block, and nodes not in a block, live in the innermost frame of the
        # single-child chain below their frame; with no frame of their own they go to the first tree.
        tops = [b for b in self.blocks if self.groups[b]["parent"] not in self.children]
        loose = [m for gid, ns in self.nodes.items() if gid not in self.children for m in ns]
        owned: dict[str | None, tuple[list[str], list[dict[str, Any]]]] = {f: ([], []) for f in self.frames}

        def owner(parent: str | None) -> str | None:
            fid = parent if parent in kids else next(iter(roots), None)
            while fid is not None and len(kids[fid]) == 1:
                fid = kids[fid][0]
            return fid

        for b in tops:
            owned.setdefault(owner(self.groups[b]["parent"]), ([], []))[0].append(b)
        for n in loose:
            owned.setdefault(owner(n["group"]), ([], []))[1].append(n)

        def place_frame(fid: str, fx: int, fy: int) -> Size:
            g = self.groups[fid]
            slot = len(self.out_frames)
            left = fx + FRAME_PAD_X
            cx, content_h = left, 0
            for child in kids[fid]:
                cx += BLOCK_GAP if cx > left else 0
                cw, ch = place_frame(child, cx, fy + FRAME_PAD_TOP)
                cx, content_h = cx + cw, max(content_h, ch)
            own_tops, own_loose = owned[fid]
            if own_tops or own_loose:
                cx += BLOCK_GAP if cx > left else 0
                used_w, used_h = self._columns(cx, fy + FRAME_PAD_TOP, fid, own_tops, own_loose)
                cx, content_h = cx + used_w, max(content_h, used_h)
            w, h = cx + FRAME_PAD_X - fx, content_h + FRAME_PAD_TOP + FRAME_PAD_X
            self.out_frames.insert(slot, Group(fid, g["label"], fx, fy, w, h, g["parent"], g["kind"],
                                               cloud=g.get("cloud")))
            return w, h

        if not roots:
            return self._columns(x, y, None, *owned.get(None, ([], [])))
        rx, height = x, 0
        for root in roots:
            w, h = place_frame(root, rx, y)
            rx, height = rx + w + BLOCK_GAP, max(height, h)
        return rx - BLOCK_GAP - x, height
