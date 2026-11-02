"""Projections of a C4 model into curated-shaped dicts, one per diagram, for the layout engine to draw."""

from dataclasses import dataclass

from cartographer.c4_model import Model, edge_text, in_scope, rollup, type_line, visible
from cartographer.c4_styles import element_label, element_size


@dataclass(frozen=True)
class View:
    slug: str
    title: str
    curated: dict


def _kind(element: dict) -> str:
    if element["type"] == "container":
        return {"store": "container_store", "queue": "container_queue"}.get(element.get("shape"), "container")
    return f"{element['type']}_ext" if element.get("external") else element["type"]


def _element_node(element: dict, group: str | None) -> dict:
    label = element_label(element["name"], type_line(element), element["description"])
    kind = _kind(element)
    return {"id": element["id"], "label": label, "service": "other", "group": group, "tf": [], "multi": False,
            "box": list(element_size(label, kind)), "c4": kind}


def _element_external(element: dict) -> dict:
    node = _element_node(element, None)
    return {"id": node["id"], "label": node["label"], "icon": "none", "box": node["box"], "c4": node["c4"],
            "evidence": []}


def _boundary(element: dict) -> dict:
    return {"id": element["id"], "label": f"{element['name']}\n{type_line(element)}", "kind": "boundary",
            "parent": None, "column": 0}


def _curated(model: Model, title: str, group: dict | None, inside: list[dict], edges: list[dict]) -> dict:
    """The diagram of `inside`, in `group` if there is one, plus whatever else the edges reach."""
    inside_ids = {e["id"] for e in inside}
    reached = {end for edge in edges for end in (edge["src"], edge["dst"])} - inside_ids
    return {
        "title": title,
        "groups": [_boundary(group)] if group else [],
        "nodes": [_element_node(e, group["id"] if group else None) for e in inside],
        "externals": [_element_external(e) for e in model["elements"] if e["id"] in reached],
        "edges": [{**edge, "evidence": []} for edge in edges],
    }


def _children(model: Model, parent: dict, kind: str) -> list[dict]:
    return [e for e in model["elements"] if e["type"] == kind and e.get("parent") == parent["id"]]


def _outsiders(model: Model) -> list[dict]:
    """The people and external systems any view may draw around its subject."""
    return [e for e in model["elements"] if e["type"] == "person" or (e["type"] == "system" and e.get("external"))]


def _rolled_up(model: Model, title: str, group: dict | None, inside: list[dict], siblings: list[dict]) -> dict:
    """A view whose edges are the model's relationships lifted to `inside`, people, external systems and
    `siblings`; edges that do not touch `inside` belong to another view."""
    shown = {e["id"] for e in [*inside, *_outsiders(model), *siblings]}
    inside_ids = {e["id"] for e in inside}
    edges = [e for e in rollup(model, shown) if {e["src"], e["dst"]} & inside_ids]
    return _curated(model, title, group, inside, edges)




def _dynamic(model: Model, system: dict, scenario: dict, title: str) -> dict:
    """The scenario's steps at container level: containers inside the system boundary, the rest outside."""
    containers = _children(model, system, "container")
    shown = {e["id"] for e in [*containers, *_outsiders(model)]}
    by_id = {r["id"]: r for r in model["relationships"]}
    edges = []
    for number, step in enumerate(scenario["steps"], 1):
        r = by_id[step]
        src, dst = visible(model, r["src"], shown), visible(model, r["dst"], shown)
        if src != dst:
            edges.append({"src": src, "dst": dst, "label": f"{number}. {edge_text(r['label'], r.get('technology'))}",
                          "dashed": r["dashed"]})
    ends = {end for edge in edges for end in (edge["src"], edge["dst"])}
    return _curated(model, title, system, [c for c in containers if c["id"] in ends], edges)


def views(model: Model) -> list[View]:
    """Every diagram the model supports, in slug order."""
    system = in_scope(model)
    name = system["name"]
    containers = _children(model, system, "container")
    context, container_title = f"System Context diagram for {name}", f"Container diagram for {name}"
    result = [
        View("1-context", context, _rolled_up(model, context, None, [system], [])),
        View("2-container", container_title, _rolled_up(model, container_title, system, containers, [])),
    ]
    for container in containers:
        components = _children(model, container, "component")
        if components:
            title = f"Component diagram for {name}: {container['name']}"
            siblings = [c for c in containers if c is not container]
            result.append(View(f"3-component-{container['id']}", title,
                               _rolled_up(model, title, container, components, siblings)))
    # 4-code-<component id> (code level) and 5-deployment go here, between the component and dynamic views
    for scenario in model.get("scenarios", []):
        title = f"Dynamic diagram for {name}: {scenario['name']}"
        result.append(View(f"6-dynamic-{scenario['id']}", title, _dynamic(model, system, scenario, title)))
    return result
