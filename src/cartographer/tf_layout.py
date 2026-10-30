"""Stage 4: lay a verified curated.json out as a left-to-right column grid and return an absolute-coordinate Diagram.

Blocks are laid out with 2, 3 and 4 node columns; the result whose bounding box is closest to A4 landscape wins.
Placement (tf_place) orders the items for few straight-line crossings. Straight lines only approximate the routed
ones, so that grid width is placed once per length weight in SPREADS and the placement whose routed result shows the
fewest defects wins: crossings plus checker violations (each is one flaw a reader sees), then bends.
"""

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from cartographer import tf_lanes
from cartographer.diagram_model import (
    Diagram,
    Edge,
    Legend,
    Title,
    bounds,
)
from cartographer.tf_aws_externals import adopt
from cartographer.tf_blocks import GAP, Blocks
from cartographer.tf_check import defects, measure
from cartographer.tf_colors import Colours
from cartographer.tf_place import place
from cartographer.tf_space import Widening, fit

ORIGIN = (40, 100)
LEGEND_W, LEGEND_LINE = 440, 18
GRID_CHOICES = (2, 3, 4)
A4_RATIO = math.sqrt(2)
SPREADS = (math.inf, 500)  # pixels of straight line that weigh as much as one crossing in placement
Curated = dict[str, Any]


def _legend(y: int) -> Legend:
    return Legend(ORIGIN[0], y, LEGEND_W, LEGEND_LINE * 4 + 8, "Line colour = destination", (),
                  "Solid line: primary request path\nDashed line: secondary, control or async")


def _edges(curated: Curated, known: set[str], labels: bool) -> tuple[Edge, ...]:
    colours = Colours(curated)
    kept = sorted((e for e in curated["edges"] if {e["src"], e["dst"]} <= known),
                  key=lambda e: (e["src"], e["dst"], e.get("label", "")))
    return tuple(Edge(e["src"], e["dst"], e.get("label", "") if labels else "", dashed=e.get("dashed", False),
                      color=colours.node(e["dst"])) for e in kept)


def _build(curated: Curated, cols: int, labels: bool) -> Diagram:
    ox, oy = ORIGIN
    left, right = tf_lanes.split(curated)
    _, frames_h = Blocks(curated, cols).place_frames(0, 0)
    frames_x = ox + (tf_lanes.width(left, frames_h) + GAP if left else 0)
    lay = Blocks(curated, cols)
    frames_w, _ = lay.place_frames(frames_x, oy)
    externals = [*tf_lanes.place(left, ox, oy, frames_h),
                 *tf_lanes.place(right, frames_x + frames_w + GAP, oy, frames_h)]
    leaves = sorted([*lay.out_leaves, *externals], key=lambda n: n.id)
    bottom = max([oy + frames_h, *(bounds(n)[3] for n in externals)]) + GAP
    return Diagram(Title(ox, 20, 1400, 60, curated["title"]), (*lay.out_frames, *lay.out_groups, *leaves),
                   _edges(curated, {n.id for n in leaves}, labels), _legend(bottom))


def _arrange(curated: Curated, cols: int, labels: bool, px_per_crossing: float) -> Diagram:
    return _build(place(curated, lambda c: _build(c, cols, labels), px_per_crossing), cols, labels)


def _defects(fitted: tuple[Diagram, list[Widening]]) -> tuple[int, int]:
    return defects(fitted[0])


def extent(diagram: Diagram) -> tuple[int, int]:
    """Width and height of everything drawn except the title: frames, leaves and the legend."""
    boxes = [bounds(n) for n in (*diagram.nodes, diagram.legend)]
    return (max(b[2] for b in boxes) - min(b[0] for b in boxes), max(b[3] for b in boxes) - min(b[1] for b in boxes))


def _off_a4(diagram: Diagram) -> float:
    w, h = extent(diagram)
    return abs(math.log(w / h / A4_RATIO))


def layout_report(curated: Curated, *, edge_labels: bool = True) -> tuple[Diagram, list[Widening]]:
    """The arrangement with the block grid width whose extent is closest to A4 landscape (ties go to fewer columns),
    routed, with the gaps that had to be widened for its lines."""
    curated = adopt(curated)
    first, *rest = SPREADS
    by_cols = {cols: _arrange(curated, cols, edge_labels, first) for cols in GRID_CHOICES}
    cols = min(GRID_CHOICES, key=lambda c: _off_a4(by_cols[c]))
    candidates = [by_cols[cols], *(_arrange(curated, cols, edge_labels, px) for px in rest)]
    return min(map(fit, candidates), key=_defects)


def layout(curated: Curated, *, edge_labels: bool = True) -> Diagram:
    return layout_report(curated, edge_labels=edge_labels)[0]


if __name__ == "__main__":
    from cartographer import gen_drawio

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("curated", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--edge-labels", choices=("on", "off"), default="on")
    args = ap.parse_args()
    data = json.loads(args.curated.read_text(encoding="utf-8"))
    stack = args.curated.name.split(".")[0]
    start = time.perf_counter()
    diagram, widened = layout_report(data, edge_labels=args.edge_labels == "on")
    drawio = gen_drawio.render(diagram, page_id=f"{stack}-architecture", page_name=data["title"])
    args.output.write_text(drawio, encoding="utf-8")
    w, h = extent(diagram)
    print(measure(drawio).summary(), f"({time.perf_counter() - start:.1f}s)")
    print(f"extent {w}x{h}, aspect {w / h:.2f}, widened: {'; '.join(map(str, widened)) or 'none'}")
