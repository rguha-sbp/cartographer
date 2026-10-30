import math
import xml.etree.ElementTree as ET

from cartographer import gen_drawio, tf_layout
from cartographer.diagram_model import BRAND_ICONS
from cartographer.tf_geom import (
    GLYPH_W,
    ICON_LABEL_PAD,
    ICON_LINE_H,
    TEXT_PAD,
    group_rect,
    groups,
    label_rect,
    label_size,
    leaves,
)
from cartographer.tf_read import read


def _curated() -> dict:
    frames = [("g_cloud", "cloud", None), ("g_region", "region", "g_cloud"), ("g_account", "account", "g_region")]
    groups_ = [{"id": i, "label": i, "kind": k, "parent": p, "column": 0} for i, k, p in frames]
    groups_.append({"id": "g_app", "label": "App", "kind": None, "parent": "g_account", "column": 0})
    nodes = [{"id": "app", "label": "App", "service": "lambda", "group": "g_app", "tf": ["x"], "multi": False}]
    externals = [{"id": "x_model", "label": "Models", "icon": "none", "service": "bedrock", "evidence": []},
                 {"id": "x_hub", "label": "GitHub", "icon": "github", "evidence": []}]
    edges = [{"src": "app", "dst": d, "label": "", "flow": "runtime", "dashed": False, "evidence": []}
             for d in ("x_model", "x_hub")]
    return {"title": "T", "groups": groups_, "nodes": nodes, "externals": externals, "edges": edges}


def _render() -> tuple[str, dict]:
    diagram = tf_layout.layout(_curated())
    return gen_drawio.render(diagram, page_id="t", page_name="t"), leaves(diagram) | {g.id: g for g in groups(diagram)}


def test_aws_service_external_sits_inside_the_region_frame_with_a_resource_icon() -> None:
    xml, by_id = _render()
    x0, y0, x1, y1 = group_rect(by_id["g_region"], 0)
    node = by_id["x_model"]
    assert x0 <= node.x and node.x + 60 <= x1 and y0 <= node.y and node.y + 60 <= y1
    style = next(c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("id") == "x_model")
    assert "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.bedrock;" in style
    assert by_id["x_hub"].x > x1 or by_id["x_hub"].x + 60 < x0


def test_brand_icon_renders_with_its_exact_style() -> None:
    xml, _ = _render()
    style = next(c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("id") == "x_hub")
    assert style == BRAND_ICONS["github"]


def _style_of(xml: str, cid: str) -> str:
    return next(c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("id") == cid)


def test_generic_icon_label_is_not_wrapped_and_reads_back_at_its_true_size() -> None:
    curated = _curated()
    curated["externals"][1] = {"id": "x_mcp", "label": "MCP servers\nremote tools", "icon": "external_toolkit",
                               "evidence": []}
    curated["edges"][1]["dst"] = "x_mcp"
    xml = gen_drawio.render(tf_layout.layout(curated), page_id="t", page_name="t")
    assert "whiteSpace" not in _style_of(xml, "x_mcp")
    drawn = leaves(read(xml))["x_mcp"]
    x0, y0, x1, y1 = label_rect(drawn)
    assert (x1 - x0, y1 - y0) == label_size("MCP servers\nremote tools") == (math.ceil(12 * GLYPH_W + TEXT_PAD),
                                                                               2 * ICON_LINE_H + ICON_LABEL_PAD)
