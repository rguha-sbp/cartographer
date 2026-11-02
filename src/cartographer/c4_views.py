"""Projections of a C4 model into curated-shaped dicts, one per diagram, for the layout engine to draw."""

import re
from dataclasses import dataclass
from pathlib import Path

from cartographer.c4_boxes import element_node
from cartographer.c4_deploy import deployment
from cartographer.c4_model import SHAPE, Model, edge_text, elements, in_scope, rollup, type_line, visible

HEADS = {"uses": "open", "inherits": "inherits", "implements": "implements"}
# Slugs of the views: the first three once per model, the rest once per container, component or scenario id.
CONTEXT, CONTAINER, DEPLOYMENT = "1-context", "2-container", "5-deployment"
COMPONENT, CODE, DYNAMIC = "3-component", "4-code", "6-dynamic"
ID = SHAPE["$defs"]["id"]["pattern"].strip("^$")


@dataclass(frozen=True)
class View:
    slug: str
    title: str
    curated: dict


def _element_external(element: dict) -> dict:
    node = element_node(element, None)
    return {"id": node["id"], "label": node["label"], "icon": node["icon"], "box": node["box"],
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
        "nodes": [element_node(e, group["id"] if group else None) for e in inside],
        "externals": [_element_external(e) for e in model["elements"] if e["id"] in reached],
        "edges": [{**edge, "evidence": []} for edge in edges],
    }


def _children(model: Model, parent: dict, kind: str) -> list[dict]:
    return [e for e in model["elements"] if e["type"] == kind and e.get("parent") == parent["id"]]


def _shown(model: Model, *parts: list[dict]) -> set[str]:
    """Ids of the parts' elements plus the people and external systems any view may draw around its subject."""
    outsiders = [e for e in model["elements"] if e["type"] == "person" or (e["type"] == "system" and e.get("external"))]
    return {e["id"] for part in (*parts, outsiders) for e in part}


def _component(model: Model, title: str, container: dict, components: list[dict], siblings: list[dict]) -> dict:
    """The container's components with the people, external systems and sibling containers they reach; edges that
    do not touch a component belong to the Container view."""
    inside = {c["id"] for c in components}
    edges = [e for e in rollup(model, _shown(model, components, siblings)) if {e["src"], e["dst"]} & inside]
    return _curated(model, title, container, components, edges)


def _dynamic(model: Model, system: dict, scenario: dict, title: str) -> dict:
    """The scenario's steps at container level: containers inside the system boundary, the rest outside."""
    containers = _children(model, system, "container")
    shown, by_id = _shown(model, containers), elements(model)
    relationships = {r["id"]: r for r in model["relationships"]}
    edges = []
    for number, step in enumerate(scenario["steps"], 1):
        r = relationships[step]
        src, dst = visible(by_id, r["src"], shown), visible(by_id, r["dst"], shown)
        if src != dst:
            edges.append({"src": src, "dst": dst, "label": f"{number}. {edge_text(r['label'], r.get('technology'))}",
                          "dashed": r["dashed"]})
    ends = {end for edge in edges for end in (edge["src"], edge["dst"])}
    return _curated(model, title, system, [c for c in containers if c["id"] in ends], edges)


def _code(model: Model, component: dict, classes: list[dict], title: str) -> dict:
    """The component's code elements and the relationships between them; links that leave it are not drawn."""
    ids = {c["id"] for c in classes}
    edges = [{"src": r["src"], "dst": r["dst"], "label": edge_text(r["label"], r.get("technology")),
              "dashed": r["dashed"] and r.get("kind", "uses") == "uses",  # the head draws inherits and implements
              "head": HEADS[r.get("kind", "uses")], "relationships": [r["id"]]}
             for r in model["relationships"] if {r["src"], r["dst"]} <= ids]
    return _curated(model, title, component, classes, edges)


def core(model: Model) -> list[View]:
    """The C4 core: Context, Container, a Component view per container with components and a Code view per
    component with code elements. People and external systems keep their edges to each other on the first two."""
    system = in_scope(model)
    name = system["name"]
    containers = _children(model, system, "container")
    context, container_title = f"System Context diagram for {name}", f"Container diagram for {name}"
    result = [
        View(CONTEXT, context, _curated(model, context, None, [system], rollup(model, _shown(model, [system])))),
        View(CONTAINER, container_title,
             _curated(model, container_title, system, containers, rollup(model, _shown(model, containers)))),
    ]
    for container in containers:
        if components := _children(model, container, "component"):
            title = f"Component diagram for {name}: {container['name']}"
            siblings = [c for c in containers if c["id"] != container["id"]]
            result.append(View(f"{COMPONENT}-{container['id']}", title,
                               _component(model, title, container, components, siblings)))
    for component in (e for e in model["elements"] if e["type"] == "component"):
        if classes := _children(model, component, "code"):
            title = f"Code diagram for {name}: {component['name']}"
            result.append(View(f"{CODE}-{component['id']}", title, _code(model, component, classes, title)))
    return result


def views(model: Model) -> list[View]:
    """Every diagram the model supports, in slug order: the core, then Deployment and Dynamic."""
    system = in_scope(model)
    name = system["name"]
    result = core(model)
    if "deployment" in model:
        title = f"Deployment diagram for {name}: {model['deployment']['environment']}"
        result.append(View(DEPLOYMENT, title, deployment(model, title)))
    for scenario in model.get("scenarios", []):
        title = f"Dynamic diagram for {name}: {scenario['name']}"
        result.append(View(f"{DYNAMIC}-{scenario['id']}", title, _dynamic(model, system, scenario, title)))
    return result


def drawio_name(name: str) -> str:
    """The .drawio that holds every view of the model named `name`, one page each."""
    return f"{name}-c4.drawio"


def written_by_c4(name: str, path: Path) -> bool:
    """Whether path is a view image a C4 build of the model named `name` writes beside its .drawio, or a view file
    an earlier build wrote, for any ids."""
    view = f"({CONTEXT}|{CONTAINER}|{DEPLOYMENT}|({COMPONENT}|{CODE}|{DYNAMIC})-{ID})"
    book = re.escape(Path(drawio_name(name)).stem)
    return re.fullmatch(f"{book}-{view}\\.svg|{re.escape(name)}-{view}\\.(drawio|svg)", path.name) is not None
