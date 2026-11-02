"""Renderer-neutral diagram types shared by hand-made models, the Terraform layout and the renderers."""

from dataclasses import dataclass
from typing import Literal

ICON = 60
ICON_LABEL = 34
BOX_W, BOX_H = 200, 56
ORIGIN = (40, 100)  # top-left of the drawing below the title; the legend starts at the same x
FRAME_TITLE_LEFT, GROUP_TITLE_LEFT = 30, 8  # a group title starts this far in: after the AWS frame icon, or plain

BLUE, RED, GREEN, PURPLE, GREY = "#147EBA", "#DD344C", "#1D8102", "#8C4FFF", "#879196"
EDGE_DEFAULT = "#545B64"
FLOW_COLORS = {"web": BLUE, "trigger": GREEN, "runtime": PURPLE, "credential": RED, "data": GREY}
FLOW_MEANINGS = {
    "web": ("Blue", "browser and user facing path"),
    "trigger": ("Green", "triggered runs (schedule, event, webhook)"),
    "runtime": ("Purple", "service to service calls at run time"),
    "credential": ("Red", "credential and secret access path"),
    "data": ("Grey", "data plumbing, audit, egress, delivery"),
}

L, R, T, B = (0, 0.5), (1, 0.5), (0.5, 0), (0.5, 1)

Port = tuple[float, float]
Point = tuple[int, int]
Kind = Literal["cloud", "region", "account", "network", "subnet", "boundary", "deployment"]
Head = Literal["open", "inherits", "implements"]


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    parent: str | None = None
    kind: Kind | None = None
    tier: str | None = None
    fill: str = "none"
    stroke: str = GREY
    cloud: str | None = None


@dataclass(frozen=True)
class Icon:
    id: str
    label: str
    icon: str
    x: int
    y: int
    parent: str | None = None


@dataclass(frozen=True)
class Box:
    id: str
    label: str
    x: int
    y: int
    w: int = 200
    h: int = 56
    parent: str | None = None
    shape: str = "none"  # what the box stands for (its node's service or icon); the notation decides its look


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    label: str = ""
    points: tuple[Point, ...] = ()
    dashed: bool = False
    color: str = EDGE_DEFAULT
    out: Port | None = None
    into: Port | None = None
    at: float = 0
    shift: Point = (0, 0)
    exact: bool = False  # `points` are the whole route, drawn as given; otherwise they only hint the connector
    out_off: Point = (0, 0)  # whole-pixel offset of the exit port from its fractional anchor
    into_off: Point = (0, 0)
    head: Head = "open"


@dataclass(frozen=True)
class LegendEntry:
    color: str
    name: str
    meaning: str


@dataclass(frozen=True)
class Legend:
    x: int
    y: int
    w: int
    h: int
    heading: str
    entries: tuple[LegendEntry, ...]
    footnote: str


@dataclass(frozen=True)
class Title:
    x: int
    y: int
    w: int
    h: int
    text: str


@dataclass(frozen=True)
class Diagram:
    title: Title
    nodes: tuple[Group | Icon | Box, ...]
    edges: tuple[Edge, ...]
    legend: Legend


def bounds(node: Group | Icon | Box | Legend) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of a placed item; an icon includes the label zone below it."""
    match node:
        case Icon():
            return node.x, node.y, node.x + ICON, node.y + ICON + ICON_LABEL
        case _:
            return node.x, node.y, node.x + node.w, node.y + node.h
