import itertools
import xml.etree.ElementTree as ET

from test_route import _fan_out, _render

from cartographer import gen_drawio, tf_layout
from cartographer.diagram_model import Diagram, Edge, Group, Icon, Legend, Title
from cartographer.tf_check import measure
from cartographer.tf_geom import LINE_GAP, PORT_GAP, leaves, parallel_gap, polyline, segments, side_of
from cartographer.tf_read import read
from cartographer.tf_route import route

HARD = ("lines_too_close", "ports_too_close", "line_near_node", "caption_far", "angled_segments",
        "caption_overlaps", "edge_through_node", "edge_through_group", "edge_through_title", "line_on_frame",
        "caption_on_node")


def _scene(nodes: tuple, edges: tuple) -> Diagram:
    return Diagram(Title(0, 0, 0, 0, ""), nodes, edges, Legend(0, 0, 0, 0, "", (), ""))


def _hard(xml: str) -> dict[str, int]:
    stats = measure(xml)
    return {k: getattr(stats, k) for k in HARD}


def test_parallel_segments_of_two_edges_keep_line_gap() -> None:
    nodes = (Icon("a", "A", "s3", 0, 100), Icon("b", "B", "s3", 500, 40), Icon("c", "C", "s3", 500, 200))
    routed = route(_scene(nodes, (Edge("a", "b"), Edge("a", "c"))))
    polys = [segments(polyline(e, leaves(routed))) for e in routed.edges]
    gaps = [parallel_gap(s, t) for s in polys[0] for t in polys[1]]
    assert all(g is None or g >= LINE_GAP for g in gaps)


def test_hub_with_twelve_edges_is_clear_everywhere() -> None:
    xml = _render(_fan_out())
    assert _hard(xml) == dict.fromkeys(HARD, 0)


def test_caption_with_one_spot_near_an_icon_stays_on_its_line() -> None:
    nodes = (Icon("a", "A", "s3", 0, 100), Icon("b", "B", "s3", 460, 100), Icon("c", "Centre label", "s3", 230, 60))
    xml = gen_drawio.render(route(_scene(nodes, (Edge("a", "b", "a fairly long caption"),))), page_id="t",
                            page_name="t")
    assert (measure(xml).caption_crowding, measure(xml).caption_far) == (0, 0)


def test_every_edge_is_axis_aligned_with_explicit_points() -> None:
    xml = _render(_fan_out())
    assert measure(xml).angled_segments == 0
    for cell in ET.fromstring(xml).iter("mxCell"):
        if cell.get("edge"):
            assert cell.find("mxGeometry/Array/mxPoint") is not None
            assert "exitPerimeter=0" in cell.get("style") and "entryPerimeter=0" in cell.get("style")
    drawn = read(xml)
    nodes = leaves(drawn)
    for e in drawn.edges:
        for (ax, ay), (bx, by) in segments(polyline(e, nodes)):
            assert ax == bx or ay == by


def test_aligned_ports_still_get_stub_points() -> None:
    nodes = (Icon("a", "A", "s3", 0, 100), Icon("b", "B", "s3", 300, 100))
    edge = route(_scene(nodes, (Edge("a", "b"),))).edges[0]
    assert len(edge.points) >= 2


def test_hub_spreads_over_sides_and_groups_ports_by_flow() -> None:
    hub = Icon("hub", "Hub", "lambda", 600, 400)
    targets = [Icon(f"r{i}", f"R{i}", "s3", 1100, 150 + i * 160) for i in range(4)]
    targets += [Icon(f"u{i}", f"U{i}", "s3", 300 + i * 220, 60) for i in range(4)]
    targets += [Icon(f"d{i}", f"D{i}", "s3", 300 + i * 220, 760) for i in range(4)]
    colours = ["#147EBA", "#1D8102"]
    edges = tuple(Edge("hub", t.id, color=colours[i % 2]) for i, t in enumerate(targets))
    routed = route(_scene((hub, *targets), edges))
    by_side: dict[str, list[tuple[int, str]]] = {}
    for e in routed.edges:
        side = side_of(e.out)
        by_side.setdefault(side, []).append((sum(e.out_off), e.color))
    assert len(by_side) >= 3
    for ports in by_side.values():
        seq = [c for _, c in sorted(ports)]
        runs = sum(a != b for a, b in itertools.pairwise(seq)) + 1
        assert runs <= len(set(seq))
        offs = sorted(o for o, _ in ports)
        assert all(b - a >= PORT_GAP for a, b in itertools.pairwise(offs))
    xml = gen_drawio.render(routed, page_id="t", page_name="t")
    assert measure(xml).ports_too_close == 0
    assert measure(xml).lines_too_close == 0


def test_node_without_room_reports_ports_too_close() -> None:
    nodes = [Icon("hub", "Hub", "lambda", 400, 300), *(Icon(f"t{i}", f"T{i}", "s3", 800, i * 100) for i in range(20))]
    routed = route(_scene(tuple(nodes), tuple(Edge("hub", f"t{i}") for i in range(20))))
    assert measure(gen_drawio.render(routed, page_id="t", page_name="t")).ports_too_close > 0


def test_line_colour_is_the_destination_group_colour() -> None:
    curated = _fan_out()
    diagram = tf_layout.layout(curated)
    group_of = {n["id"]: n["group"] for n in curated["nodes"]}
    by_side: dict[tuple[str, str], dict[str, set[str]]] = {}
    for e in diagram.edges:
        by_side.setdefault((e.src, side_of(e.out)), {}).setdefault(e.color, set()).add(group_of[e.dst])
    assert all(len(groups) == 1 for colours in by_side.values() for groups in colours.values())
    assert len({e.color for e in diagram.edges}) == 3


def test_checker_counts_a_line_running_along_a_frame_border() -> None:
    nodes = (Group("g", "G", 100, 100, 300, 300), Icon("o", "O", "s3", 0, 0), Icon("i", "I", "s3", 130, 300, "g"))
    along = Edge("o", "i", points=((60, 30), (106, 30), (106, 330)), out=(1, 0.5), into=(0, 0.5), exact=True)
    assert measure(gen_drawio.render(_scene(nodes, (along,)), page_id="t", page_name="t")).line_on_frame == 1


def test_line_keeps_line_gap_from_frame_borders_it_runs_beside() -> None:
    for ox, ix in ((60, 130), (68, 110)):
        nodes = (Group("g", "G", 100, 100, 300, 300), Icon("o", "O", "s3", ox, -40), Icon("i", "I", "s3", ix, 300, "g"))
        xml = gen_drawio.render(route(_scene(nodes, (Edge("o", "i"),))), page_id="t", page_name="t")
        assert (measure(xml).line_on_frame, _hard(xml)) == (0, dict.fromkeys(HARD, 0))
