"""A notation decides how a laid-out diagram looks and explains itself: the draw.io value and style of its boxes and
groups, its legend, the colour of each line and the air between boxes stacked one above another. The AWS notation is the layer 7 look."""

import html
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cartographer.diagram_model import EDGE_DEFAULT, FRAME_TITLE_LEFT, GROUP_TITLE_LEFT, ORIGIN, Box, Group, Legend
from cartographer.tf_blocks import GAP
from cartographer.tf_colors import Colours

LEGEND_W, LEGEND_LINE = 440, 18
Curated = dict[str, Any]
Cell = tuple[str, str]  # a vertex's draw.io value (HTML) and style

FRAME_STYLES = {
    "cloud": "group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;fontColor=#232F3E;dashed=0",
    "region": "group_region;strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=1",
    "account": "group_account;strokeColor=#CD2264;fillColor=none;fontColor=#CD2264;dashed=0",
    "vpc": "group_vpc2;strokeColor=#8C4FFF;fillColor=none;fontColor=#AAB7B8;dashed=0",
    "subnet-public": "group_security_group;strokeColor=#7AA116;fillColor=none;fontColor=#248814;dashed=0",
    "subnet-private": "group_security_group;strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=0",
    "subnet-isolated": "group_security_group;strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=1",
}


@dataclass(frozen=True)
class Notation:
    box: Callable[[Box], Cell]
    group: Callable[[Group], Cell]
    legend: Callable[[Curated, int], Legend]  # the legend placed at height y below the drawing
    edge_colour: Callable[[Curated], Callable[[str], str]]  # line colour by destination id
    row_gap: int  # vertical clearance between boxes stacked one above another


def html_value(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


def aws_group(g: Group) -> Cell:
    """An AWS frame by its kind, else a plain group in its purpose colour."""
    if g.kind:
        key = f"subnet-{g.tier}" if g.kind == "subnet" else g.kind
        return html_value(g.label), (
            f"points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],"
            f"[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
            f"fontSize=12;fontStyle=1;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
            f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{FRAME_STYLES[key]};verticalAlign=top;align=left;"
            f"spacingLeft={FRAME_TITLE_LEFT};")
    return html_value(g.label), (
        f"rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;fillColor={g.fill};"
        f"strokeColor={g.stroke};dashed=1;verticalAlign=top;align=left;spacingLeft={GROUP_TITLE_LEFT};fontSize=12;"
        f"fontStyle=1;fontColor=#232F3E;")


def _aws_box(b: Box) -> Cell:
    """Every box alike: a grey rounded rectangle, whatever its shape."""
    return html_value(b.label), (f"rounded=1;whiteSpace=wrap;html=1;fillColor=#F2F3F3;strokeColor={EDGE_DEFAULT};"
                                 f"fontColor=#232F3E;fontSize=12;arcSize=12;")


def _aws_legend(curated: Curated, y: int) -> Legend:
    return Legend(ORIGIN[0], y, LEGEND_W, LEGEND_LINE * 4 + 8, "Line colour = destination", (),
                  "Solid line: primary request path\nDashed line: secondary, control or async")


def _destination_colour(curated: Curated) -> Callable[[str], str]:
    return Colours(curated).node


AWS = Notation(_aws_box, aws_group, _aws_legend, _destination_colour, row_gap=GAP)
