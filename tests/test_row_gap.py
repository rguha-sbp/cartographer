"""The notation decides the vertical clearance between boxes stacked one above another; C4 gets more than L7."""

from itertools import permutations

from cartographer import tf_layout
from cartographer.c4_styles import C4
from cartographer.diagram_model import bounds
from cartographer.notation import AWS, Notation
from cartographer.tf_blocks import GAP

BOX = [260, 112]


def _box(nid: str, group: str | None) -> dict:
    return {"id": nid, "label": nid, "service": "container", "group": group, "tf": [], "multi": False, "box": BOX}


def _curated() -> dict:
    """Two boundaries stacked in a parent, one holding a grid of rows, loose boxes under them and a lane of
    externals: every place where boxes stack."""
    groups = [{"id": "sys", "label": "System", "kind": "boundary", "parent": None, "column": 1},
              *({"id": g, "label": g, "kind": "boundary", "parent": "sys", "column": 1} for g in ("a", "b"))]
    nodes = [*(_box(f"a{i}", "a") for i in range(6)), _box("b0", "b"), _box("loose0", None), _box("loose1", None)]
    externals = [{"id": f"x{i}", "label": f"x{i}", "icon": "system_ext", "evidence": [], "box": BOX}
                 for i in range(4)]
    return {"title": "T", "groups": groups, "nodes": nodes, "externals": externals, "edges": []}


def _least_vertical_gap(notation: Notation) -> int:
    """The least clearance between any two disjoint rectangles of which one sits right under the other."""
    rects = [bounds(n) for n in tf_layout.layout(_curated(), notation=notation).nodes]
    return min(lo[1] - up[3] for up, lo in permutations(rects, 2)
               if up[3] <= lo[1] and up[0] < lo[2] and lo[0] < up[2])


def test_c4_stacks_boxes_at_least_its_row_gap_apart() -> None:
    assert C4.row_gap >= 2 * GAP
    assert _least_vertical_gap(C4) >= C4.row_gap


def test_l7_row_gap_is_unchanged() -> None:
    assert AWS.row_gap == GAP == 40
    assert _least_vertical_gap(AWS) == GAP
