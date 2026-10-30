import json
import xml.etree.ElementTree as ET

from cartographer import gen_drawio, tf_layout, tfdiagram
from cartographer.diagram_model import Icon
from cartographer.tf_geom import leaves
from cartographer.tf_read import read

CURATED = {
    "title": "Mini architecture",
    "groups": [{"id": "app", "label": "Application", "kind": None, "parent": None, "column": 1}],
    "nodes": [
        {"id": "fn", "label": "Worker", "service": "Lambda", "group": "app", "tf": ["aws_lambda_function.fn"],
         "multi": False},
        {"id": "data", "label": "Data", "service": "S3", "group": "app", "tf": ["aws_s3_bucket.data"],
         "multi": False},
    ],
    "externals": [{"id": "users", "label": "Users", "icon": "none", "evidence": []}],
    "edges": [
        {"src": "users", "dst": "fn", "label": "invoke", "flow": "web", "dashed": False, "evidence": []},
        {"src": "fn", "dst": "data", "label": "read objects", "flow": "data", "dashed": False, "evidence": []},
    ],
}


def test_layout_renders_edges_between_existing_vertices() -> None:
    xml = gen_drawio.render(tf_layout.layout(CURATED), page_id="mini-architecture", page_name=CURATED["title"])
    cells = list(ET.fromstring(xml).iter("mxCell"))
    vertices = {c.get("id") for c in cells if c.get("vertex") == "1"}
    edges = [c for c in cells if c.get("edge") == "1"]
    assert len(edges) == 2
    for edge in edges:
        assert edge.get("source") in vertices
        assert edge.get("target") in vertices


def test_non_aws_node_with_an_icon_renders_as_that_icon() -> None:
    nodes = [*CURATED["nodes"], {"id": "mon", "label": "Datadog monitors\nalerts", "service": "other", "icon": "alert",
                                 "group": "app", "tf": ["datadog_monitor.x"], "multi": False}]
    xml = gen_drawio.render(tf_layout.layout({**CURATED, "nodes": nodes}), page_id="m", page_name="m")
    style = next(c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("id") == "mon")
    assert "shape=mxgraph.aws4.alert;" in style
    assert isinstance(leaves(read(xml))["mon"], Icon)


def test_schema_offers_node_icons_from_the_external_icon_enum() -> None:
    props = json.loads(tfdiagram.schema_text())["properties"]
    node_icon = props["nodes"]["items"]["properties"]["icon"]
    assert node_icon["enum"] == props["externals"]["items"]["properties"]["icon"]["enum"]
    assert "icon" not in props["nodes"]["items"]["required"]
