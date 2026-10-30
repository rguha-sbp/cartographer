import math
from itertools import combinations

from cartographer import tf_layout
from cartographer.diagram_model import Diagram, Edge, Icon, Legend, Title
from cartographer.tf_aws_externals import BLOCK_ID
from cartographer.tf_geom import groups, leaves
from cartographer.tf_place import objective


def _square(edges: list[tuple[str, str]]) -> Diagram:
    nodes = tuple(Icon(i, i, "lambda", x, y) for i, x, y in (("a", 0, 0), ("b", 300, 0), ("c", 0, 300),
                                                                ("d", 300, 300)))
    return Diagram(Title(0, 0, 10, 10, "t"), nodes, tuple(Edge(s, d) for s, d in edges),
                   Legend(0, 0, 1, 1, "", (), ""))


def test_objective_counts_straight_lines_that_cross_and_weighs_length_against_them() -> None:
    crossed, parallel = _square([("a", "d"), ("b", "c")]), _square([("a", "b"), ("c", "d")])
    assert objective(crossed, math.inf) == 1
    assert objective(parallel, math.inf) == 0
    assert objective(parallel, 300) == 2  # two 300 px lines at 300 px per crossing


def _frames() -> list[dict]:
    frames = [("g_cloud", "cloud", None), ("g_region", "region", "g_cloud"), ("g_account", "account", "g_region")]
    return [{"id": i, "label": i, "kind": k, "parent": p, "column": 0} for i, k, p in frames]


def _node(nid: str, group: str) -> dict:
    return {"id": nid, "label": nid, "service": "lambda", "group": group, "tf": [nid], "multi": False}


def _edge(src: str, dst: str) -> dict:
    return {"src": src, "dst": dst, "label": "", "flow": "runtime", "dashed": False, "evidence": []}


def test_managed_services_block_sits_beside_its_callers_not_below_everything() -> None:
    blocks = [{"id": f"g{c}{r}", "label": f"B{c}{r}", "kind": None, "parent": "g_account", "column": c}
              for c in range(3) for r in range(3)]
    nodes = [_node(f"n{c}{r}{k}", f"g{c}{r}") for c in range(3) for r in range(3) for k in range(2)]
    externals = [{"id": "x_s3", "label": "S3", "icon": "none", "service": "s3", "evidence": []}]
    curated = {"title": "T", "groups": [*_frames(), *blocks], "nodes": nodes, "externals": externals,
               "edges": [_edge("n000", "x_s3"), _edge("n001", "x_s3"), _edge("n000", "n100")]}
    diagram = tf_layout.layout(curated)
    by_id = {g.id: g for g in groups(diagram)}
    managed, caller = by_id[BLOCK_ID], by_id["g00"]
    assert managed.y < by_id["g02"].y
    assert managed.x <= caller.x + caller.w + 200


def test_externals_are_ordered_by_the_height_of_what_they_talk_to() -> None:
    blocks = [{"id": f"g{r}", "label": f"B{r}", "kind": None, "parent": "g_account", "column": 0} for r in range(3)]
    nodes = [_node(f"n{r}", f"g{r}") for r in range(3)]
    externals = [{"id": i, "label": i, "icon": "users", "evidence": []} for i in ("x_low", "x_mid", "x_high")]
    edges = [_edge("x_low", "n2"), _edge("x_mid", "n1"), _edge("x_high", "n0")]
    curated = {"title": "T", "groups": [*_frames(), *blocks], "nodes": nodes, "externals": externals, "edges": edges}
    placed = leaves(tf_layout.layout(curated))
    lanes = {e["src"]: placed[e["dst"]].y for e in edges}
    for a, b in combinations(lanes, 2):
        if placed[a].x == placed[b].x:
            assert (placed[a].y < placed[b].y) == (lanes[a] < lanes[b])
