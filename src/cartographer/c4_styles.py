"""C4 notation: element boxes, boundaries and deployment nodes in the standard C4 palette, one neutral line colour,
and a key that explains only what the diagram shows."""

import html
import math
import textwrap
from collections.abc import Callable
from dataclasses import dataclass

from cartographer.diagram_model import GROUP_TITLE_LEFT, ORIGIN, Box, Group, Legend, LegendEntry
from cartographer.notation import LEGEND_LINE, LEGEND_W, Cell, Curated, Notation, aws_group, html_value
from cartographer.tf_blocks import shape
from cartographer.tf_geom import GLYPH_W

LINE = "#707070"  # every relationship line, and the grey of boundaries and deployment nodes
WHITE, DARK = "#FFFFFF", "#232F3E"
DESCRIPTION_WRAP = 32
TEXT_LINE_H, TEXT_PAD_X, TEXT_PAD_Y, PERSON_HEAD = 16, 24, 32, 60
MIN_W = 200

ROUNDED, PERSON = "rounded=1;arcSize=6;", "shape=mxgraph.c4.person2;verticalAlign=bottom;spacingBottom=16;"
STORE, QUEUE = "shape=cylinder3;", "shape=cylinder3;direction=south;"


@dataclass(frozen=True)
class Element:
    name: str  # as the key names it
    meaning: str
    shape: str
    fill: str
    stroke: str
    font: str
    head: int = 0  # extra height above the text: the person's head


ELEMENTS = {
    "person": Element("Person", "a user of the system", PERSON, "#08427B", "#08427B", WHITE, PERSON_HEAD),
    "person_ext": Element("External person", "a user outside the organisation", PERSON, "#999999", "#999999", DARK,
                          PERSON_HEAD),
    "system": Element("Software system", "the system in scope", ROUNDED, "#1168BD", "#1168BD", WHITE),
    "system_ext": Element("External software system", "a system it depends on or serves", ROUNDED, "#999999",
                          "#999999", DARK),
    "container": Element("Container", "an application or service that runs on its own", ROUNDED, "#438DD5",
                         "#438DD5", WHITE),
    "container_store": Element("Data store", "a container that stores data", STORE, "#438DD5", "#438DD5", WHITE),
    "container_queue": Element("Queue", "a container that carries messages", QUEUE, "#438DD5", "#438DD5", WHITE),
    "component": Element("Component", "a part of a container", ROUNDED, "#85BBF0", "#85BBF0", DARK),
    "code": Element("Code element", "a class, interface or module", ROUNDED, WHITE, LINE, DARK),
}

HEAD_KEYS = {"inherits": "Hollow triangle: inherits", "implements": "Dashed line, hollow triangle: implements"}


@dataclass(frozen=True)
class GroupKind:
    name: str
    meaning: str
    fill: str
    dashed: int


GROUP_KINDS = {
    "boundary": GroupKind("Boundary", "dashed: what belongs to one system or container", "none", 1),
    "deployment": GroupKind("Deployment node", "solid: infrastructure the containers run on", WHITE, 0),
}


def element_label(name: str, type_line: str, description: str) -> str:
    """Name, `[Type: technology]` and the description wrapped at DESCRIPTION_WRAP characters, one per line."""
    return "\n".join([name, type_line, *textwrap.wrap(description, DESCRIPTION_WRAP)])


def element_size(label: str, kind: str) -> tuple[int, int]:
    """A box wide and tall enough for its label; a person adds room for the head."""
    lines = label.split("\n")
    return (max(MIN_W, math.ceil(max(map(len, lines)) * GLYPH_W + TEXT_PAD_X)),
            len(lines) * TEXT_LINE_H + TEXT_PAD_Y + ELEMENTS[kind].head)


def _box(b: Box) -> Cell:
    """An element box in its C4 shape and colours: the name in bold 14 px over the type line and description."""
    e = ELEMENTS[b.shape]
    name, *rest = (html.escape(line, quote=False) for line in b.label.split("\n"))
    return "<br>".join([f'<b style="font-size:14px">{name}</b>', *rest]), (
        f"{e.shape}whiteSpace=wrap;html=1;fillColor={e.fill};strokeColor={e.stroke};fontColor={e.font};"
        f"fontSize=12;align=center;")


def _group(g: Group) -> Cell:
    """A boundary or deployment node in C4 grey; a cloud, region or network frame as AWS draws it."""
    if g.kind not in GROUP_KINDS:
        return aws_group(g)
    f = GROUP_KINDS[g.kind]
    return html_value(g.label), (
        f"rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;fillColor={f.fill};"
        f"strokeColor={LINE};dashed={f.dashed};verticalAlign=top;align=left;spacingLeft={GROUP_TITLE_LEFT};"
        f"fontSize=12;fontStyle=1;fontColor={DARK};")


def _legend(curated: Curated, y: int) -> Legend:
    leaves = [*curated["nodes"], *curated["externals"]]
    shown = {shape(n) for n in leaves} | {g["kind"] for g in curated["groups"]}
    entries = [LegendEntry(e.stroke, e.name, e.meaning) for k, e in ELEMENTS.items() if k in shown]
    entries += [LegendEntry(LINE, f.name, f.meaning) for k, f in GROUP_KINDS.items() if k in shown]
    dashed = {e["dashed"] for e in curated["edges"] if e.get("head", "open") == "open"}
    heads = {e.get("head") for e in curated["edges"]}
    lines = [text for flag, text in ((False, "Solid line: synchronous"), (True, "Dashed line: asynchronous"))
             if flag in dashed]
    lines += [text for head, text in HEAD_KEYS.items() if head in heads]
    return Legend(ORIGIN[0], y, LEGEND_W, LEGEND_LINE * (2 + len(entries) + len(lines)) + 8, "Key",
                  tuple(entries), "\n".join(lines))


def _neutral(curated: Curated) -> Callable[[str], str]:
    return lambda _dst: LINE


C4 = Notation(_box, _group, _legend, _neutral)
