"""Externals live in side lanes outside the frames: an icon cell when they carry an icon, else a plain box."""

from typing import Any

from cartographer.diagram_model import BOX_W, ICON, Box, Icon, has_icon
from cartographer.tf_blocks import CELL_H, GAP, cell_w

BOX_PITCH = 100
Lane = list[dict[str, Any]]


def split(curated: dict[str, Any]) -> tuple[Lane, Lane]:
    """An external's `lane` when placement set one; else those that only call in go left and everything else
    (including edgeless ones) goes right."""
    srcs = {e["src"] for e in curated["edges"]}
    dsts = {e["dst"] for e in curated["edges"]}
    externals = curated["externals"]
    left = [x for x in externals
            if x.get("lane", "left" if x["id"] in srcs and x["id"] not in dsts else "right") == "left"]
    return left, [x for x in externals if x not in left]


def _has_icon(x: dict[str, Any]) -> bool:
    return has_icon(x.get("icon", "none"))


def _cell(lane: Lane) -> tuple[int, int]:
    """Cell size shared by the lane: wide and tall enough for its widest and tallest member."""
    return (max((cell_w([x["label"]]) if _has_icon(x) else BOX_W for x in lane), default=0),
            max((CELL_H if _has_icon(x) else BOX_PITCH for x in lane), default=0))


def _subcols(lane: Lane, height: int) -> int:
    return 2 if len(lane) * _cell(lane)[1] > height else 1


def width(lane: Lane, height: int) -> int:
    """Lane width; a lane taller than `height` wraps into two sub-columns."""
    n = _subcols(lane, height)
    return n * _cell(lane)[0] + (n - 1) * GAP


def place(lane: Lane, x: int, y: int, height: int) -> list[Icon | Box]:
    """Row-major in the sub-columns, so lane order stays top to bottom."""
    (cw, ch), n = _cell(lane), _subcols(lane, height)
    out: list[Icon | Box] = []
    for i, ext in enumerate(lane):
        cx, cy = x + (i % n) * (cw + GAP), y + (i // n) * ch
        if _has_icon(ext):
            out.append(Icon(ext["id"], ext["label"], ext["icon"], cx + (cw - ICON) // 2, cy))
        else:
            out.append(Box(ext["id"], ext["label"], cx + (cw - BOX_W) // 2, cy))
    return out
