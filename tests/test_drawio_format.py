import re
import xml.etree.ElementTree as ET

import pytest

from cartographer import gen_drawio
from cartographer.diagram_model import B, Box, Diagram, Edge, Group, Icon, L, Legend, LegendEntry, R, T, Title


def _diagram() -> Diagram:
    nodes = (
        Group("acct", "Shop account", 0, 100, 700, 300, kind="account"),
        Icon("cdn", "CloudFront\nCDN", "cloudfront", 40, 160, parent="acct"),
        Icon("api", "orders API\norder handling", "lambda", 240, 160, parent="acct"),
        Icon("ddb", "orders table\ncustomer's orders", "dynamodb", 440, 160, parent="acct"),
        Box("stripe", "Stripe\npayments", 800, 180),
    )
    edges = (
        Edge("cdn", "api", "invokes", points=((150, 190), (200, 190)), out=R, into=L),
        Edge("api", "ddb", "reads orders", points=((350, 190), (400, 190)), out=R, into=L),
        Edge("api", "stripe", "charges", points=((270, 300), (900, 300)), out=B, into=T, dashed=True),
    )
    legend = Legend(0, 500, 300, 80, "Legend", (LegendEntry("#147EBA", "Blue", "web path"),), "note")
    return Diagram(Title(0, 0, 400, 40, "Shop: AWS architecture"), nodes, edges, legend)


@pytest.fixture(scope="module")
def xml() -> str:
    return gen_drawio.render(_diagram(), page_id="shop-architecture", page_name="Shop architecture")


@pytest.fixture(scope="module")
def cells(xml: str) -> list[ET.Element]:
    return list(ET.fromstring(xml).iter("mxCell"))


def test_mxfile_has_no_version_attribute(xml: str) -> None:
    assert "version" not in ET.fromstring(xml).attrib


def test_attributes_are_ordered_id_first_and_as_last(xml: str) -> None:
    for tag in re.findall(r"<[A-Za-z]+ [^>]*>", xml):
        names = re.findall(r'([A-Za-z]+)="', tag)
        if "id" in names:
            assert names[0] == "id", tag
        if "as" in names:
            assert names[-1] == "as", tag


def test_indentation_is_two_spaces(xml: str) -> None:
    indents = [len(line) - len(line.lstrip(" ")) for line in xml.splitlines()]
    assert set(indents) > {0, 2}
    assert all(n % 2 == 0 for n in indents)
    assert not any(line.startswith("\t") for line in xml.splitlines())


def test_apostrophe_is_written_as_numeric_entity(xml: str) -> None:
    assert "&#39;" in xml
    assert "'" not in xml


def test_every_edge_has_ports_and_points(cells: list[ET.Element]) -> None:
    edges = [c for c in cells if c.get("edge") == "1"]
    assert len(edges) == 3
    for e in edges:
        style = e.get("style", "")
        assert "exitX=" in style and "entryX=" in style
        assert e.find("mxGeometry/Array[@as='points']") is not None


def test_vertex_ids_are_unique(cells: list[ET.Element]) -> None:
    ids = [c.get("id") for c in cells if c.get("vertex") == "1"]
    assert len(ids) == len(set(ids)) >= 6
