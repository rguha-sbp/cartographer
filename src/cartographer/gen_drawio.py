"""Render a Diagram as a draw.io file: icons in each cloud's own shapes, lines, title and legend here, boxes and groups
as the notation draws them."""

import html
import xml.etree.ElementTree as ET

from cartographer import files, icons
from cartographer.diagram_model import (
    ICON,
    Box,
    Diagram,
    Edge,
    Group,
    Icon,
    Legend,
    Point,
    Port,
    Title,
)
from cartographer.notation import LAYER7, Notation, html_value

END_ARROWS = {
    "open": "endArrow=open;endFill=0;",
    "inherits": "endArrow=block;endFill=0;",
    "implements": "endArrow=block;endFill=0;dashed=1;",
}

TITLE_STYLE = "text;html=1;align=left;verticalAlign=top;fontSize=18;fontStyle=1;fontColor=#232F3E;whiteSpace=wrap;"
LEGEND_STYLE = ("rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=8;fillColor=#FFFFFF;"
                "strokeColor=#879196;fontSize=12;")


def _el(owner: ET.Element | None, tag: str, **attrs: str | float) -> ET.Element:
    """Create an element with draw.io attribute order: id first, as last, the rest alphabetical."""
    keys = sorted(attrs, key=lambda k: (k == "as_", k != "id", k))
    el = ET.Element(tag, {k.rstrip("_"): str(attrs[k]) for k in keys})
    if owner is not None:
        owner.append(el)
    return el


def _port(kind: str, p: Port | None, off: Point, exact: bool) -> str:
    if not p:
        return ""
    return f"{kind}X={p[0]};{kind}Y={p[1]};{kind}Dx={off[0]};{kind}Dy={off[1]};" + (f"{kind}Perimeter=0;" if exact else "")


def _legend_html(lg: Legend) -> str:
    lines = [f"<b>{html.escape(lg.heading, quote=False)}</b>"]
    lines += [f"<font color='{e.color}'>{e.name}</font>: {html.escape(e.meaning, quote=False)}" for e in lg.entries]
    return "<br>".join(lines) + "<br>" + html_value(lg.footnote)


class DrawioRenderer:
    def __init__(self, notation: Notation) -> None:
        self.notation = notation
        self.root = ET.Element("root")
        _el(self.root, "mxCell", id="0")
        _el(self.root, "mxCell", id="1", parent="0")
        self.abs_pos: dict[str, tuple[int, int]] = {}
        self.edge_count = 0

    def _vertex(self, cid: str, value: str, style: str, x: int, y: int, w: int, h: int, parent: str | None) -> None:
        self.abs_pos[cid] = (x, y)
        px, py = self.abs_pos[parent] if parent else (0, 0)
        cell = _el(self.root, "mxCell", id=cid, value=value, style=style, vertex="1", parent=parent or "1")
        _el(cell, "mxGeometry", x=x - px, y=y - py, width=w, height=h, as_="geometry")

    def title(self, t: Title) -> None:
        self._vertex("title", html_value(t.text), TITLE_STYLE, t.x, t.y, t.w, t.h, None)

    def node(self, n: Group | Icon | Box) -> None:
        match n:
            case Group():
                self._vertex(n.id, *self.notation.group(n), n.x, n.y, n.w, n.h, n.parent)
            case Icon() if icons.known(n.icon):
                self._vertex(n.id, html_value(n.label), icons.style(n.icon), n.x, n.y, ICON, ICON, n.parent)
            case Icon():  # an icon name the registry does not know is a box of icon size
                self.node(Box(n.id, n.label, n.x, n.y, ICON, ICON, n.parent))
            case Box():
                self._vertex(n.id, *self.notation.box(n), n.x, n.y, n.w, n.h, n.parent)

    def edge(self, e: Edge) -> None:
        connector = "rounded=0;" if e.exact else "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
        style = (f"{connector}html=1;{END_ARROWS[e.head]}"
                 f"strokeColor={e.color};strokeWidth=1.5;fontSize=12;fontColor=#232F3E;"
                 f"labelBackgroundColor=#FFFFFF;{'dashed=1;' if e.dashed else ''}{_port('exit', e.out, e.out_off, e.exact)}"
                 f"{_port('entry', e.into, e.into_off, e.exact)}")
        self.edge_count += 1
        cell = _el(self.root, "mxCell", id=f"e{self.edge_count}", value=html_value(e.label), style=style, edge="1",
                   parent="1", source=e.src, target=e.dst)
        geo = _el(cell, "mxGeometry", relative="1", as_="geometry", **({"x": e.at} if e.at else {}))
        if e.points:
            arr = _el(geo, "Array", as_="points")
            for px, py in e.points:
                _el(arr, "mxPoint", x=px, y=py)
        if e.shift != (0, 0):
            _el(geo, "mxPoint", x=e.shift[0], y=e.shift[1], as_="offset")

    def legend(self, lg: Legend) -> None:
        self._vertex("legend", _legend_html(lg), LEGEND_STYLE, lg.x, lg.y, lg.w, lg.h, None)


def page(diagram: Diagram, *, page_id: str, page_name: str, notation: Notation = LAYER7) -> ET.Element:
    """The diagram as one page of an mxfile."""
    r = DrawioRenderer(notation)
    r.title(diagram.title)
    for n in diagram.nodes:
        r.node(n)
    for e in diagram.edges:
        r.edge(e)
    r.legend(diagram.legend)
    result = ET.Element("diagram", id=page_id, name=page_name)
    model = ET.SubElement(result, "mxGraphModel", dx="2977", dy="1683", grid="1", gridSize="10", guides="1",
                          tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth="2620",
                          pageHeight="1640", math="0", shadow="0")
    model.append(r.root)
    return result


def render(diagram: Diagram, *, page_id: str, page_name: str, notation: Notation = LAYER7) -> str:
    """The diagram as a one-page mxfile."""
    return files.mxfile([page(diagram, page_id=page_id, page_name=page_name, notation=notation)])
