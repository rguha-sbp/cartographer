"""A notation decides how a laid-out diagram looks and explains itself: the draw.io value and style of its boxes and
groups, its legend, the colour of each line and the air between boxes stacked one above another. LAYER7 is the
Layer 7 look of every cloud."""

import html
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cartographer.clouds import CLOUDS
from cartographer.diagram_model import EDGE_DEFAULT, GROUP_TITLE_LEFT, ORIGIN, Box, Group, Legend
from cartographer.tf_blocks import GAP
from cartographer.tf_colors import Colours

GROUP_TINT = 8  # percent opacity of a group's fill in its own colour: visible, yet quiet behind icons and lines

LEGEND_W, LEGEND_LINE = 440, 18
Curated = dict[str, Any]
Cell = tuple[str, str]  # a vertex's draw.io value (HTML) and style


@dataclass(frozen=True)
class Notation:
    box: Callable[[Box], Cell]
    group: Callable[[Group], Cell]
    legend: Callable[[Curated, int], Legend]  # the legend placed at height y below the drawing
    edge_colour: Callable[[Curated], Callable[[str], str]]  # line colour by destination id
    row_gap: int  # vertical clearance between boxes stacked one above another


def html_value(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


def cloud_group(g: Group) -> Cell:
    """A frame in the style its cloud draws it, else a group tinted faintly in its purpose colour.

    The tint sits behind the icons and lines, so the group reads as a background area; nested groups darken a little.
    """
    if g.kind:
        key = f"subnet-{g.tier}" if g.kind == "subnet" else g.kind
        if g.cloud not in CLOUDS:
            raise ValueError(f"group {g.id}: {g.kind} frame has cloud {g.cloud!r}, which is not a known cloud")
        return html_value(g.label), CLOUDS[g.cloud].frame_styles[key]
    return html_value(g.label), (
        f"rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;"
        f"fillColor={g.colour};fillOpacity={GROUP_TINT};strokeColor={g.colour};"
        f"verticalAlign=top;align=left;spacingLeft={GROUP_TITLE_LEFT};fontSize=12;fontStyle=1;fontColor=#232F3E;")


def _layer7_box(b: Box) -> Cell:
    """Every box alike: a grey rounded rectangle, whatever its shape."""
    return html_value(b.label), (f"rounded=1;whiteSpace=wrap;html=1;fillColor=#F2F3F3;strokeColor={EDGE_DEFAULT};"
                                 f"fontColor=#232F3E;fontSize=12;arcSize=12;")


def _layer7_legend(curated: Curated, y: int) -> Legend:
    return Legend(ORIGIN[0], y, LEGEND_W, LEGEND_LINE * 4 + 8, "Line colour = destination", (),
                  "Solid line: primary request path\nDashed line: secondary, control or async")


def _destination_colour(curated: Curated) -> Callable[[str], str]:
    return Colours(curated).node


LAYER7 = Notation(_layer7_box, cloud_group, _layer7_legend, _destination_colour, row_gap=GAP)
