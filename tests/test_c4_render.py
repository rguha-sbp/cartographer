import html
import inspect

import pytest

from cartographer import c4_styles, gen_drawio, notation, tf_layout
from cartographer.c4_styles import C4, element_label, element_size
from cartographer.diagram_model import Box, Diagram, Edge, Group, Legend, Title


def _container(nid: str) -> dict:
    return {"id": nid, "label": element_label(nid, "[Container: Python]", "Serves the shop"), "service": "container",
            "group": None, "tf": [], "multi": False, "box": [260, 112]}


def _curated(nodes: list[dict], edges: list[dict]) -> dict:
    return {"title": "Container diagram for Shop", "groups": [], "nodes": nodes, "externals": [], "edges": edges}


def _one_container_curated() -> dict:
    return _curated([_container("api")], [])


def _two_container_curated() -> dict:
    edge = {"src": "api", "dst": "db", "label": "reads", "dashed": False, "evidence": []}
    return _curated([_container("api"), _container("db")], [edge])


def _render_with_head(head: str) -> str:
    nodes = (Box("a", "A", 0, 0), Box("b", "B", 400, 0))
    diagram = Diagram(Title(0, 0, 100, 40, "t"), nodes, (Edge("a", "b", head=head),),
                      Legend(0, 200, 100, 40, "Key", (), ""))
    return gen_drawio.render(diagram, page_id="p", page_name="t")


def test_l7_output_unchanged() -> None:  # existing tests cover it; this one asserts AWS is the default notation
    assert tf_layout.layout.__kwdefaults__["notation"] is notation.AWS
    assert tf_layout.layout_report.__kwdefaults__["notation"] is notation.AWS


def test_c4_box_is_sized_and_styled() -> None:
    d = tf_layout.layout(_one_container_curated(), notation=c4_styles.C4)
    box = next(n for n in d.nodes if n.id == "api")
    assert (box.w, box.h, box.shape) == (260, 112, "container")
    xml = gen_drawio.render(d, page_id="p", page_name="t", notation=c4_styles.C4)
    assert "fillColor=#438DD5" in xml and "<b" in html.unescape(xml)


def test_c4_external_box_is_sized_in_its_lane() -> None:
    person = {"id": "user", "label": element_label("User", "[Person]", "Buys things"), "icon": "person",
              "box": [220, 140], "evidence": []}
    edge = {"src": "user", "dst": "api", "label": "uses", "dashed": False, "evidence": []}
    d = tf_layout.layout({**_one_container_curated(), "externals": [person], "edges": [edge]}, notation=c4_styles.C4)
    box = next(n for n in d.nodes if n.id == "user")
    assert (box.w, box.h, box.shape) == (220, 140, "person")
    assert "shape=mxgraph.c4.person2" in gen_drawio.render(d, page_id="p", page_name="t", notation=c4_styles.C4)


def test_c4_legend_lists_only_used_kinds() -> None:
    d = tf_layout.layout(_one_container_curated(), notation=c4_styles.C4)
    assert d.legend.heading == "Key"
    assert [e.name for e in d.legend.entries] == ["Container"]
    assert d.legend.footnote == ""


def test_c4_legend_explains_only_used_line_styles() -> None:
    d = tf_layout.layout(_two_container_curated(), notation=c4_styles.C4)
    assert d.legend.footnote == "Solid line: synchronous"


def test_c4_legend_lists_boundaries() -> None:
    curated = _one_container_curated()
    curated["groups"] = [{"id": "shop", "label": "Shop\n[Software System]", "kind": "boundary", "parent": None,
                          "column": 0}]
    curated["nodes"][0]["group"] = "shop"
    d = tf_layout.layout(curated, notation=c4_styles.C4)
    assert [e.name for e in d.legend.entries] == ["Container", "Boundary"]
    xml = gen_drawio.render(d, page_id="p", page_name="t", notation=c4_styles.C4)
    style = next(c for c in xml.splitlines() if 'id="shop"' in c)
    assert "dashed=1" in style and "fillColor=none" in style


def test_c4_lines_are_neutral() -> None:
    edges = tf_layout.layout(_two_container_curated(), notation=c4_styles.C4).edges
    assert {e.color for e in edges} == {"#707070"}


def test_inherits_head_renders_hollow_triangle() -> None:
    assert "endArrow=block;endFill=0" in _render_with_head("inherits")
    assert "endArrow=block;endFill=0;dashed=1" in _render_with_head("implements")
    assert "endArrow=open;endFill=0" in _render_with_head("open")


def test_curated_head_reaches_the_edge() -> None:
    curated = _two_container_curated()
    curated["edges"][0]["head"] = "inherits"
    assert tf_layout.layout(curated, notation=c4_styles.C4).edges[0].head == "inherits"


def test_element_label_wraps_the_description() -> None:
    assert element_label("API", "[Container: Python]", "x" * 40) == f"API\n[Container: Python]\n{'x' * 32}\nxxxxxxxx"


def test_element_size_grows_with_text() -> None:
    short = element_size(element_label("API", "[Container: Python]", "x"), "container")
    long = element_size(element_label("API", "[Container: Python]", "x" * 64), "container")
    assert long[1] > short[1]
    assert short == (200, 3 * 16 + 32)
    assert element_size(element_label("API", "[Container: Python]", "x"), "person")[1] == short[1] + 60


def test_box_html_bolds_the_name() -> None:
    assert C4.box(Box("a", "A & B\n[Container]\ndoes x", 0, 0, shape="container"))[0] == (
        '<b style="font-size:14px">A &amp; B</b><br>[Container]<br>does x')


def test_no_flashy_styles() -> None:
    for kind in ("person", "system", "container", "container_store", "component", "code"):
        style = C4.box(Box("a", "A", 0, 0, shape=kind))[1]
        assert not any(k in style for k in ("shadow=1", "gradientColor=#", "sketch=1", "flowAnimation", "glass=1"))


def _render_nodes(nodes: tuple, note: notation.Notation) -> str:
    diagram = Diagram(Title(0, 0, 100, 40, "t"), nodes, (), Legend(0, 300, 100, 40, "Key", (), ""))
    return gen_drawio.render(diagram, page_id="p", page_name="t", notation=note)


def test_c4_groups_render_with_c4_styles() -> None:
    xml = _render_nodes((Group("n", "Node", 0, 0, 300, 200, kind="deployment"),), c4_styles.C4)
    assert "fillColor=#FFFFFF" in xml and "dashed=0" in xml


def test_c4_deployment_frames_keep_the_aws_frame_style() -> None:
    frame = (Group("r", "eu-west-1", 0, 0, 300, 200, kind="region"),)
    assert _render_nodes(frame, c4_styles.C4) == _render_nodes(frame, notation.AWS)


@pytest.mark.parametrize(("note", "fill"), [(notation.AWS, "#F2F3F3"), (c4_styles.C4, "#438DD5")])
def test_the_notation_draws_the_box(note: notation.Notation, fill: str) -> None:
    assert f"fillColor={fill}" in _render_nodes((Box("a", "A\n[Container]", 0, 0, shape="container"),), note)


def test_the_renderer_knows_no_c4() -> None:
    assert "c4" not in inspect.getsource(gen_drawio).lower()


def test_c4_legend_explains_arrowheads_that_appear() -> None:
    curated = _two_container_curated()
    curated["edges"][0]["head"] = "implements"
    footnote = tf_layout.layout(curated, notation=c4_styles.C4).legend.footnote
    assert "Dashed line, hollow triangle: implements" in footnote and "inherits" not in footnote
    curated["edges"][0]["head"] = "inherits"
    assert "Hollow triangle: inherits" in tf_layout.layout(curated, notation=c4_styles.C4).legend.footnote
