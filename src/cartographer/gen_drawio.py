"""Render a Diagram as a draw.io file with AWS 4 shapes and connected edges."""

import html
import xml.etree.ElementTree as ET

from cartographer.diagram_model import (
    AWS_ICONS,
    BRAND_ICONS,
    FRAME_TITLE_LEFT,
    GENERIC_ICONS,
    GROUP_TITLE_LEFT,
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
    has_icon,
)

GROUP_STYLES = {
    "cloud": "group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;fontColor=#232F3E;dashed=0",
    "region": "group_region;strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=1",
    "account": "group_account;strokeColor=#CD2264;fillColor=none;fontColor=#CD2264;dashed=0",
    "vpc": "group_vpc2;strokeColor=#8C4FFF;fillColor=none;fontColor=#AAB7B8;dashed=0",
}

TITLE_STYLE = "text;html=1;align=left;verticalAlign=top;fontSize=18;fontStyle=1;fontColor=#232F3E;whiteSpace=wrap;"
LEGEND_STYLE = ("rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=8;fillColor=#FFFFFF;"
                "strokeColor=#879196;fontSize=12;")


def _html_value(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


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


def _group_style(g: Group) -> str:
    if g.kind:
        return (f"points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],"
                f"[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
                f"fontSize=12;fontStyle=1;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
                f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{GROUP_STYLES[g.kind]};verticalAlign=top;align=left;"
                f"spacingLeft={FRAME_TITLE_LEFT};")
    return (f"rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;fillColor={g.fill};"
            f"strokeColor={g.stroke};dashed=1;verticalAlign=top;align=left;spacingLeft={GROUP_TITLE_LEFT};fontSize=12;fontStyle=1;"
            f"fontColor=#232F3E;")


def _icon_style(i: Icon) -> str:
    if i.service in BRAND_ICONS:
        return BRAND_ICONS[i.service]
    if i.service in GENERIC_ICONS:
        return (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={GENERIC_ICONS[i.service]};"
                f"strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                f"fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{i.service};")
    return (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={AWS_ICONS[i.service]};"
            f"strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
            f"fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.resourceIcon;"
            f"resIcon=mxgraph.aws4.{i.service};")


def _box_style(b: Box) -> str:
    return (f"rounded=1;whiteSpace=wrap;html=1;fillColor={b.fill};strokeColor={b.stroke};fontColor=#232F3E;"
            f"fontSize=12;arcSize=12;")


def _legend_html(lg: Legend) -> str:
    lines = [f"<b>{html.escape(lg.heading, quote=False)}</b>"]
    lines += [f"<font color='{e.color}'>{e.name}</font>: {html.escape(e.meaning, quote=False)}" for e in lg.entries]
    return "<br>".join(lines) + "<br>" + _html_value(lg.footnote)


class DrawioRenderer:
    def __init__(self) -> None:
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
        self._vertex("title", _html_value(t.text), TITLE_STYLE, t.x, t.y, t.w, t.h, None)

    def node(self, n: Group | Icon | Box) -> None:
        match n:
            case Group():
                self._vertex(n.id, _html_value(n.label), _group_style(n), n.x, n.y, n.w, n.h, n.parent)
            case Icon():
                style = _icon_style(n) if has_icon(n.service) else _box_style(Box(n.id, n.label, 0, 0))
                self._vertex(n.id, _html_value(n.label), style, n.x, n.y, ICON, ICON, n.parent)
            case Box():
                self._vertex(n.id, _html_value(n.label), _box_style(n), n.x, n.y, n.w, n.h, n.parent)

    def edge(self, e: Edge) -> None:
        connector = "rounded=0;" if e.exact else "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
        style = (f"{connector}html=1;endArrow=open;"
                 f"endFill=0;strokeColor={e.color};strokeWidth=1.5;fontSize=12;fontColor=#232F3E;"
                 f"labelBackgroundColor=#FFFFFF;{'dashed=1;' if e.dashed else ''}{_port('exit', e.out, e.out_off, e.exact)}"
                 f"{_port('entry', e.into, e.into_off, e.exact)}")
        self.edge_count += 1
        cell = _el(self.root, "mxCell", id=f"e{self.edge_count}", value=_html_value(e.label), style=style, edge="1",
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


def render(diagram: Diagram, *, page_id: str, page_name: str) -> str:
    r = DrawioRenderer()
    r.title(diagram.title)
    for n in diagram.nodes:
        r.node(n)
    for e in diagram.edges:
        r.edge(e)
    r.legend(diagram.legend)
    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    page = ET.SubElement(mxfile, "diagram", id=page_id, name=page_name)
    model = ET.SubElement(page, "mxGraphModel", dx="2977", dy="1683", grid="1", gridSize="10", guides="1",
                          tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth="2620",
                          pageHeight="1640", math="0", shadow="0")
    model.append(r.root)
    ET.indent(mxfile, space="  ")
    return ET.tostring(mxfile, encoding="unicode").replace("'", "&#39;") + "\n"

