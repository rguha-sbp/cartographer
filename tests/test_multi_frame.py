from cartographer import gen_drawio, tf_layout
from cartographer.tf_check import measure
from cartographer.tf_geom import groups, leaves

# Only AWS frame styles exist so far: the second tree is a second cloud frame of the same kind.
BASE = {"format": 2, "title": "Two trees", "externals": []}


def _frame(gid: str, kind: str, parent: str | None) -> dict:
    return {"id": gid, "label": gid, "kind": kind, "parent": parent, "column": 0, "cloud": "aws"}


def _block(gid: str, parent: str) -> dict:
    return {"id": gid, "label": gid, "kind": None, "parent": parent, "column": 0}


def _node(nid: str, icon: str, group: str) -> dict:
    return {"id": nid, "label": nid, "icon": f"aws:{icon}", "group": group, "tf": [], "multi": False}


def _curated(extra_groups: list[dict], nodes: list[dict], edges: list[tuple[str, str]] = ()) -> dict:
    frames = [_frame("c1", "cloud", None), _frame("r1", "region", "c1"), _frame("c2", "cloud", None),
              _frame("r2", "region", "c2")]
    return {**BASE, "groups": [*frames, *extra_groups], "nodes": nodes,
            "edges": [{"src": s, "dst": d, "label": "calls", "flow": "runtime", "dashed": False, "evidence": []}
                      for s, d in edges]}


TWO_CLOUDS = _curated([_block("b1", "r1"), _block("b2", "r2")],
                      [_node("fn", "lambda", "b1"), _node("db", "rds", "b2")], [("fn", "db")])


def _placed(curated: dict) -> dict:
    return {g.id: g for g in groups(tf_layout.layout(curated))}


def _disjoint(a, b) -> bool:
    return a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


def _inside(inner, outer) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y and inner.x + inner.w <= outer.x + outer.w
            and inner.y + inner.h <= outer.y + outer.h)


def test_two_clouds_side_by_side_do_not_overlap() -> None:
    placed = _placed(TWO_CLOUDS)
    assert _disjoint(placed["c1"], placed["c2"])
    assert placed["c1"].x < placed["c2"].x
    assert _inside(placed["b1"], placed["r1"]) and _inside(placed["r1"], placed["c1"])
    assert _inside(placed["b2"], placed["r2"]) and _inside(placed["r2"], placed["c2"])


def test_two_regions_in_one_cloud() -> None:
    curated = {**BASE, "groups": [_frame("c", "cloud", None), _frame("r1", "region", "c"), _frame("r2", "region", "c"),
                                  _block("b1", "r1"), _block("b2", "r2")],
               "nodes": [_node("fn", "lambda", "b1"), _node("db", "rds", "b2")], "edges": []}
    placed = _placed(curated)
    assert _disjoint(placed["r1"], placed["r2"]) and placed["r1"].x < placed["r2"].x
    assert _inside(placed["r1"], placed["c"]) and _inside(placed["r2"], placed["c"])
    assert _inside(placed["b1"], placed["r1"]) and _inside(placed["b2"], placed["r2"])


def test_cross_cloud_edge_has_no_rule_violations() -> None:
    diagram = tf_layout.layout(TWO_CLOUDS)
    stats = measure(gen_drawio.render(diagram, page_id="p", page_name="p"))
    assert stats.edges == 1 and stats.violations == 0


def test_nodes_without_a_group_go_to_the_first_tree() -> None:
    diagram = tf_layout.layout(_curated([_block("b2", "r2")], [_node("db", "rds", "b2"), _node("free", "s3", None)]))
    placed, icon = {g.id: g for g in groups(diagram)}, leaves(diagram)["free"]
    assert placed["c1"].x <= icon.x < placed["c1"].x + placed["c1"].w
    assert placed["r1"].y <= icon.y < placed["r1"].y + placed["r1"].h
