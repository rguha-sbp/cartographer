"""Read a draw.io file back into a Diagram of absolute boxes and edges, the way draw.io places them."""

import html
import re
import xml.etree.ElementTree as ET

from cartographer.diagram_model import Box, Diagram, Edge, Group, Icon, Legend, Title
from cartographer.gen_drawio import GROUP_STYLES

SKIP = {"title", "legend"}
KINDS = {f"mxgraph.aws4.{style.split(';')[0]}": key.split("-")[0] for key, style in GROUP_STYLES.items()}


def _text(value: str) -> str:
    return html.unescape(re.sub(r"<br>", "\n", value))


def _style(style: str) -> dict[str, str]:
    return dict(kv.split("=", 1) for kv in style.split(";") if "=" in kv)


def _node(cell: ET.Element, x: int, y: int) -> Group | Icon | Box:
    geo, style = cell.find("mxGeometry"), cell.get("style", "")
    w, h = round(float(geo.get("width"))), round(float(geo.get("height")))
    label, cid = _text(cell.get("value", "")), cell.get("id")
    if "container=1" in style:
        return Group(cid, label, x, y, w, h, kind=KINDS.get(_style(style).get("grIcon")))
    if "verticalLabelPosition=bottom" in style:
        return Icon(cid, label, "", x, y)
    return Box(cid, label, x, y, w, h)


def _edge(cell: ET.Element) -> Edge:
    geo, style = cell.find("mxGeometry"), _style(cell.get("style", ""))
    port = lambda k: (float(style[f"{k}X"]), float(style[f"{k}Y"])) if f"{k}X" in style else None
    points = tuple((round(float(p.get("x"))), round(float(p.get("y")))) for p in geo.findall("Array/mxPoint"))
    offset = geo.find("mxPoint[@as='offset']")
    shift = (round(float(offset.get("x"))), round(float(offset.get("y")))) if offset is not None else (0, 0)
    off = lambda k: (round(float(style.get(f"{k}Dx", 0))), round(float(style.get(f"{k}Dy", 0))))
    return Edge(cell.get("source"), cell.get("target"), _text(cell.get("value", "")), points, out=port("exit"),
                into=port("entry"), at=float(geo.get("x", 0)), shift=shift, out_off=off("exit"), into_off=off("entry"))


def read(drawio: str) -> Diagram:
    """Vertices with absolute positions resolved through their parents, and edges as ports, points, label spot."""
    cells = {c.get("id"): c for c in ET.fromstring(drawio).iter("mxCell")}
    origin: dict[str, tuple[int, int]] = {}

    def at(cid: str) -> tuple[int, int]:
        if cid not in cells or cells[cid].find("mxGeometry") is None:
            return 0, 0
        if cid not in origin:
            geo = cells[cid].find("mxGeometry")
            px, py = at(cells[cid].get("parent"))
            origin[cid] = px + round(float(geo.get("x", 0))), py + round(float(geo.get("y", 0)))
        return origin[cid]

    nodes = tuple(_node(c, *at(i)) for i, c in cells.items() if c.get("vertex") and i not in SKIP)
    edges = tuple(_edge(c) for c in cells.values() if c.get("edge"))
    return Diagram(Title(0, 0, 0, 0, ""), nodes, edges, Legend(0, 0, 0, 0, "", (), ""))
