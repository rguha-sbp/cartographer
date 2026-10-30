from dataclasses import replace

from cartographer import gen_drawio, tf_layout
from cartographer.diagram_model import Diagram, Edge, Group, Icon, Legend, Title
from cartographer.tf_check import measure
from cartographer.tf_geom import GLYPH_W, ICON_LINE_H, crosses, groups, leaves, polyline, segments, title_rect
from cartographer.tf_labels import Captions
from cartographer.tf_read import read
from cartographer.tf_route import route

TARGETS = [f"t{c}{i}" for c in range(3) for i in range(4)]


def _fan_out() -> dict:
    groups = [{"id": "src", "label": "Source", "kind": None, "parent": None, "column": 0}]
    nodes = [{"id": "hub", "label": "Runtime", "service": "lambda", "group": "src", "tf": ["x"], "multi": False}]
    for c in range(3):
        groups.append({"id": f"g{c}", "label": f"Targets {c}", "kind": None, "parent": None, "column": c + 1})
        nodes += [{"id": f"t{c}{i}", "label": f"Target {c}{i}", "service": "s3", "group": f"g{c}", "tf": ["x"],
                   "multi": False} for i in range(4)]
    edges = [{"src": "hub", "dst": t, "label": f"to {t}", "flow": "runtime", "dashed": False,
              "evidence": []} for t in TARGETS]
    return {"title": "Fan out", "groups": groups, "nodes": nodes, "externals": [], "edges": edges}


def _render(curated: dict) -> str:
    return gen_drawio.render(tf_layout.layout(curated), page_id="fan-architecture", page_name="Fan out")


def test_fan_out_has_no_overlaps() -> None:
    stats = measure(_render(_fan_out()))
    assert stats.edges == 12
    assert (stats.caption_overlaps, stats.edge_through_node, stats.caption_far, stats.edge_through_group,
            stats.lines_too_close, stats.caption_on_node) == (0,) * 6


def test_routing_is_deterministic() -> None:
    assert _render(_fan_out()) == _render(_fan_out())


def test_edges_carry_ports_and_label_positions() -> None:
    edges = tf_layout.layout(_fan_out()).edges
    assert all(e.out and e.into for e in edges)
    assert all(-1 <= e.at <= 1 for e in edges)
    assert len({(e.out, e.out_off) for e in edges}) > 1


def test_labels_off_leaves_captions_empty_but_routes_edges() -> None:
    edges = tf_layout.layout(_fan_out(), edge_labels=False).edges
    assert all(e.label == "" and e.at == 0 and e.out for e in edges)


def _scene(nodes: tuple, edges: tuple) -> Diagram:
    return Diagram(Title(0, 0, 0, 0, ""), nodes, edges, Legend(0, 0, 0, 0, "", (), ""))


def _render_diagram(diagram: Diagram) -> str:
    return gen_drawio.render(diagram, page_id="t", page_name="t")


def test_edge_goes_round_groups_it_does_not_belong_to() -> None:
    stacked = (Group("a", "Group A", 100, 100, 200, 100), Group("b", "Group B", 100, 220, 200, 100))
    nodes = (*stacked, Icon("left", "Left", "s3", 0, 120), Icon("right", "Right", "s3", 400, 120))
    routed = route(_scene(nodes, (Edge("left", "right", "reads"),)))
    poly = polyline(routed.edges[0], leaves(routed))
    assert not any(crosses(s, (g.x, g.y, g.x + g.w, g.y + g.h)) for g in groups(routed) for s in segments(poly))
    stats = measure(_render_diagram(routed))
    assert (stats.edge_through_group, stats.caption_on_line, stats.caption_on_node) == (0, 0, 0)


def test_edge_may_enter_the_group_it_ends_in() -> None:
    nodes = (Group("a", "Group A", 100, 100, 300, 140), Icon("left", "Left", "s3", 0, 130),
             Icon("inside", "Inside", "s3", 300, 130, "a"))
    routed = route(_scene(nodes, (Edge("left", "inside"),)))
    assert measure(_render_diagram(routed)).edge_through_group == 0
    assert len(routed.edges[0].points) <= 2


def test_caption_moves_off_another_edges_line() -> None:
    nodes = (Icon("a", "A", "s3", 0, 100), Icon("b", "B", "s3", 600, 100), Icon("c", "C", "s3", 120, 0),
             Icon("d", "D", "s3", 120, 300))
    edges = (Edge("a", "b", "a long caption"), Edge("c", "d"))
    routed = route(_scene(nodes, edges))
    assert measure(_render_diagram(routed)).caption_on_line == 0
    assert routed.edges[0].shift != (0, 0) or routed.edges[0].at != 0


def test_checker_reads_what_the_renderer_wrote() -> None:
    diagram = tf_layout.layout(_fan_out())
    drawn = read(_render(_fan_out()))
    assert len(drawn.edges) == len(diagram.edges)
    assert all(a.points == b.points and a.shift == b.shift for a, b in zip(drawn.edges, diagram.edges))
    assert set(leaves(drawn)) == set(leaves(diagram))


def test_routed_edges_are_drawn_as_given() -> None:
    xml = _render(_fan_out())
    assert "edgeStyle" not in xml


def test_title_band_covers_every_line_of_a_group_title() -> None:
    plain = Group("g", "AI services\nmemory, guardrail, RAG", 100, 100, 400, 300)
    x0, y0, x1, y1 = title_rect(plain)
    assert (x0, y0) == (100, 100)
    assert x1 - x0 >= 8 + 22 * GLYPH_W and y1 - y0 >= 2 * ICON_LINE_H
    framed = title_rect(replace(plain, kind="vpc"))
    assert framed[2] - x1 == 22  # frames start their title after the frame icon


def test_edge_goes_round_the_title_of_the_group_it_ends_in() -> None:
    nodes = (Group("g", "A wide group title\nsecond line", 100, 100, 400, 300), Icon("out", "Out", "s3", 130, -40),
             Icon("in", "In", "s3", 130, 250, "g"))
    xml = _render_diagram(route(_scene(nodes, (Edge("out", "in", "reads"),))))
    drawn = read(xml)
    assert {g.id: g.kind for g in groups(drawn)} == {"g": None}
    stats = measure(xml)
    assert (stats.edge_through_title, stats.edge_through_node, stats.caption_on_line) == (0, 0, 0)


def test_caption_crossed_by_a_later_route_is_placed_again_off_it() -> None:
    captions = Captions({}, [], [[], []])
    poly = [(0, 100), (400, 100)]
    captions.place(0, poly, "a caption")
    x0, y0, x1, _ = captions.taken[0]
    captions.add_route(1, [((x0 + x1) // 2, y0 - 50), ((x0 + x1) // 2, y0 + 80)])
    assert not captions.clear(0)
    captions.place(0, poly, "a caption")
    assert captions.clear(0)
