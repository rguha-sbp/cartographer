from cartographer import tf_layout
from cartographer.tf_geom import groups
from cartographer.tf_hub import CENTRE, EAST, WEST, centre, hub


def _frames() -> list[dict]:
    frames = [("g_cloud", "cloud", None), ("g_region", "region", "g_cloud"), ("g_account", "account", "g_region")]
    return [{"id": i, "label": i, "kind": k, "cloud": "aws", "parent": p, "column": 0} for i, k, p in frames]


def _block(bid: str, column: int, parent: str = "g_account") -> dict:
    return {"id": bid, "label": bid, "kind": None, "parent": parent, "column": column}


def _node(nid: str, group: str) -> dict:
    return {"id": nid, "label": nid, "icon": "aws:lambda", "group": group, "tf": [nid], "multi": False}


def _edge(src: str, dst: str) -> dict:
    return {"src": src, "dst": dst, "label": "", "flow": "runtime", "dashed": False, "evidence": []}


def _star(spokes: int = 6) -> dict:
    """A hub in the first of four columns, with two spokes in every other block and one edge between two spokes."""
    blocks = [_block("core", 0), _block("inner", 0, parent="core"), *(_block(f"b{i}", i % 4) for i in range(1, 4))]
    nodes = [_node("hub", "inner"), *(_node(f"s{i}", f"b{1 + i % 3}") for i in range(spokes))]
    edges = [*(_edge("hub", f"s{i}") for i in range(spokes)), _edge("s0", "s1")]
    return {"format": 2, "source": "terraform", "title": "t", "groups": [*_frames(), *blocks], "nodes": nodes,
            "externals": [], "edges": edges, "omitted": []}


def test_the_hub_has_at_least_twice_the_edges_of_any_other_end() -> None:
    assert hub(_star()) == "hub"  # 6 edges against 2


def test_no_hub_without_a_clear_lead() -> None:
    curated = _star(spokes=3)
    curated["edges"] += [_edge("s0", "s2"), _edge("s1", "s2")]  # 3 edges against 2 for s0, s1 and s2
    assert hub(curated) is None


def test_an_external_is_never_the_hub() -> None:
    curated = _star()
    curated["externals"] = [{"id": "users", "label": "users"}]
    curated["edges"] = [_edge("users", n["id"]) for n in curated["nodes"]]
    assert hub(curated) is None


def test_the_hub_block_takes_the_centre_and_the_others_are_seeded_west_and_east_by_their_edges_to_it() -> None:
    curated, free = centre(_star())
    column = {g["id"]: g["column"] for g in curated["groups"]}
    assert column["core"] == CENTRE
    assert column["inner"] == 0  # a nested block keeps its own column
    assert (column["b1"], column["b2"], column["b3"]) == (WEST, EAST, WEST)
    assert free == {"b1", "b2", "b3"}


def test_without_a_hub_centre_changes_nothing() -> None:
    curated = _star(spokes=3)
    curated["edges"] += [_edge("s0", "s2"), _edge("s1", "s2")]
    assert centre(curated) == (curated, frozenset())


def test_the_hub_block_is_laid_out_amid_the_others() -> None:
    boxes = {g.id: g for g in groups(tf_layout.layout(_star()))}

    def mid(bid: str) -> tuple[float, float]:
        b = boxes[bid]
        return b.x + b.w / 2, b.y + b.h / 2

    hub_x, hub_y = mid("core")
    xs, ys = zip(*(mid(b) for b in ("b1", "b2", "b3")), strict=True)
    assert min(xs) <= hub_x <= max(xs)
    assert min(ys) < hub_y < max(ys)
