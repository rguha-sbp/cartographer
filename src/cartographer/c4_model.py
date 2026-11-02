"""The C4 model: one flat list of elements and relationships that every view projects from."""

from collections import defaultdict
from pathlib import Path
from typing import Any

Model = dict[str, Any]

SCHEMA = Path(__file__).with_name("c4.schema.json")

_TYPE_NAMES = {"person": "Person", "system": "Software System", "container": "Container", "component": "Component"}


class RollupError(Exception):
    """Relationships that collapse onto one edge of a view but cannot share a label."""

    def __init__(self, pair: tuple[str, str], relationships: list[str]):
        super().__init__(f"{pair[0]}->{pair[1]}: relationships {', '.join(relationships)} need a shared summary and technology")
        self.pair = pair
        self.relationships = relationships


def elements(model: Model) -> dict[str, dict]:
    return {e["id"]: e for e in model["elements"]}


def in_scope(model: Model) -> dict:
    """The system being drawn: the one software system that is not external."""
    (system,) = (e for e in model["elements"] if e["type"] == "system" and not e.get("external"))
    return system


def ancestors(model: Model, eid: str) -> list[str]:
    """Parents of eid, nearest first."""
    by_id = elements(model)
    chain = []
    while parent := by_id[eid].get("parent"):
        chain.append(parent)
        eid = parent
    return chain


def visible(model: Model, eid: str, shown: set[str]) -> str | None:
    """The element that stands for eid in a view: itself, else its nearest shown ancestor."""
    return next((e for e in [eid, *ancestors(model, eid)] if e in shown), None)


def type_line(element: dict) -> str:
    if element["type"] == "code":
        return f"<<{element.get('stereotype', 'class')}>>"
    name = _TYPE_NAMES[element["type"]]
    if element["type"] in ("container", "component") and element.get("technology"):
        return f"[{name}: {element['technology']}]"
    return f"[{name}]"


def edge_text(label: str, technology: str | None) -> str:
    return f"{label}\n[{technology}]" if technology else label


def _edge_label(pair: tuple[str, str], parts: list[dict]) -> str:
    """One relationship keeps its own label; several need one text: their shared summary, else their shared label,
    over their shared technology."""
    texts = {edge_text(r["label"] if len(parts) == 1 else r.get("summary", r["label"]), r.get("technology"))
             for r in parts}
    if len(texts) > 1:
        raise RollupError(pair, sorted(r["id"] for r in parts))
    return texts.pop()


def rollup(model: Model, shown: set[str]) -> list[dict]:
    """Relationships lifted to the shown elements, one edge per ordered pair, naming the relationships behind it."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in model["relationships"]:
        src, dst = visible(model, r["src"], shown), visible(model, r["dst"], shown)
        if src and dst and src != dst:
            groups[src, dst].append(r)
    return [
        {"src": src, "dst": dst, "label": _edge_label((src, dst), parts), "dashed": all(r["dashed"] for r in parts),
         "relationships": sorted(r["id"] for r in parts)}
        for (src, dst), parts in sorted(groups.items())
    ]
