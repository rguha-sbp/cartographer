"""A notation decides how a laid-out diagram explains itself: its legend and the colour of each line."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cartographer.diagram_model import ORIGIN, Legend
from cartographer.tf_colors import Colours

LEGEND_W, LEGEND_LINE = 440, 18
Curated = dict[str, Any]


@dataclass(frozen=True)
class Notation:
    legend: Callable[[Curated, int], Legend]  # the legend placed at height y below the drawing
    edge_colour: Callable[[Curated], Callable[[str], str]]  # line colour by destination id


def _aws_legend(curated: Curated, y: int) -> Legend:
    return Legend(ORIGIN[0], y, LEGEND_W, LEGEND_LINE * 4 + 8, "Line colour = destination", (),
                  "Solid line: primary request path\nDashed line: secondary, control or async")


def _destination_colour(curated: Curated) -> Callable[[str], str]:
    return Colours(curated).node


AWS = Notation(_aws_legend, _destination_colour)
