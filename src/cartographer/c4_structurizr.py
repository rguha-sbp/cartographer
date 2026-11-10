"""The C4 model as a Structurizr DSL workspace, so one model can also be explored interactively: Structurizr's
viewers drill down from Context to Container to Component, and `structurizr export -format static` turns the
workspace into a static site.

Structurizr's implied relationships are turned off. Each rolled-up edge of a core view is written as an explicit
relationship with the text the draw.io page shows (its own label, else the shared summary), so a Structurizr view
and the matching page of the .drawio carry the same arrows. Code elements are left out: Structurizr models nothing
below a component.
"""

import re
from collections.abc import Iterator

from cartographer import c4_views
from cartographer.c4_model import Model, edge_parts, elements, in_scope, visible

_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_KINDS = {"person": "person", "system": "softwareSystem", "container": "container", "component": "component"}
_STYLES = (
    ('element "Person"', ("shape person", "background #08427b", "color #ffffff")),
    ('element "Software System"', ("background #1168bd", "color #ffffff")),
    ('element "Container"', ("background #438dd5", "color #ffffff")),
    ('element "Component"', ("background #85bbf0", "color #000000")),
    ('element "External"', ("background #999999", "color #ffffff")),
    ('element "Store"', ("shape cylinder",)),
    ('element "Queue"', ("shape pipe",)),
    ('relationship "Async"', ("dashed true",)),
    ('relationship "Relationship"', ("dashed false",)),
)


def dsl_name(name: str) -> str:
    """The workspace written beside the .drawio of the model named `name`."""
    return f"{name}-c4.dsl"


def _q(text: str | None) -> str:
    return '"' + (text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _evidence(evidence: list[dict]) -> str:
    parts = []
    for item in evidence:
        if "fact" in item:
            parts.append(f"fact {item['fact']}")
        elif "file" in item:
            parts.append(f"{item['file']}:{item['line']}")
        else:
            parts.append(f"stated: {item['stated']}")
    return "; ".join(parts)


class _Ids:
    """DSL identifiers for model and deployment ids: letters, digits and underscores, unique."""

    def __init__(self) -> None:
        self._by_id: dict[str, str] = {}
        self._taken: set[str] = set()

    def __getitem__(self, raw: str) -> str:
        if raw not in self._by_id:
            base = _UNSAFE.sub("_", raw)
            ident, n = base, 2
            while ident in self._taken:
                ident, n = f"{base}_{n}", n + 1
            self._by_id[raw] = ident
            self._taken.add(ident)
        return self._by_id[raw]


class _Lines:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def add(self, text: str) -> None:
        self.lines.append("    " * self.depth + text if text else "")

    def open(self, text: str) -> None:
        self.add(text + " {")
        self.depth += 1

    def close(self) -> None:
        self.depth -= 1
        self.add("}")


def _tags(element: dict) -> list[str]:
    tags = ["External"] if element.get("external") else []
    shape = element.get("shape")
    return tags + (["Store"] if shape == "store" else ["Queue"] if shape == "queue" else [])


def _element(out: _Lines, ids: _Ids, element: dict, children: dict[str, list[dict]]) -> None:
    technology = f" {_q(element.get('technology'))}" if element["type"] in ("container", "component") else ""
    out.open(f"{ids[element['id']]} = {_KINDS[element['type']]} {_q(element['name'])} "
             f"{_q(element['description'])}{technology}")
    if tags := _tags(element):
        out.add("tags " + " ".join(_q(t) for t in tags))
    out.open("properties")
    out.add(f'"evidence" {_q(_evidence(element["evidence"]))}')
    out.close()
    for child in children.get(element["id"], []):
        _element(out, ids, child, children)
    out.close()


def _relationship(out: _Lines, ids: _Ids, src: str, dst: str, text: str, technology: str | None, dashed: bool,
                  props: dict[str, str]) -> None:
    out.open(f"{ids[src]} -> {ids[dst]} {_q(text)} {_q(technology)}")
    if dashed:
        out.add('tags "Async"')
    out.open("properties")
    for key, value in props.items():
        out.add(f"{_q(key)} {_q(value)}")
    out.close()
    out.close()


def rolled_up(model: Model) -> Iterator[tuple[str, str, str, str | None, bool, list[str]]]:
    """Each edge of a core view that is not a relationship of the model itself, once per ordered pair:
    (src, dst, text, technology, dashed, ids of the relationships behind it)."""
    by_id = {r["id"]: r for r in model["relationships"]}
    own = {(r["src"], r["dst"]) for r in model["relationships"]}
    seen: set[tuple[str, str]] = set()
    for view in c4_views.core(model):
        if view.slug.startswith(c4_views.CODE):
            continue
        for edge in view.curated["edges"]:
            pair = (edge["src"], edge["dst"])
            if pair in own or pair in seen:
                continue
            seen.add(pair)
            parts = [by_id[rid] for rid in edge["relationships"]]
            text, technology = edge_parts(pair, parts)
            yield (*pair, text, technology, edge["dashed"], edge["relationships"])


def _steps(model: Model, system: dict, scenario_id: str) -> list[tuple[str, str, str]]:
    """The scenario's steps at container level, as the Dynamic view draws them: (src, dst, label)."""
    by_id = elements(model)
    shown = {e["id"] for e in model["elements"]
             if (e["type"] == "container" and e.get("parent") == system["id"])
             or e["type"] == "person" or (e["type"] == "system" and e.get("external"))}
    relationships = {r["id"]: r for r in model["relationships"]}
    (scenario,) = (s for s in model["scenarios"] if s["id"] == scenario_id)
    steps = []
    for step in scenario["steps"]:
        r = relationships[step]
        src, dst = visible(by_id, r["src"], shown), visible(by_id, r["dst"], shown)
        if src != dst:
            steps.append((src, dst, r["label"]))
    return steps


def _deployment(out: _Lines, ids: _Ids, model: Model) -> None:
    deployment = model["deployment"]
    nodes = deployment["nodes"]
    kids: dict[str | None, list[dict]] = {}
    for node in nodes:
        kids.setdefault(node.get("parent"), []).append(node)
    hosted: dict[str, list[str]] = {}
    for instance in deployment["instances"]:
        hosted.setdefault(instance["node"], []).append(instance["container"])

    def emit(node: dict) -> None:
        holds = node["id"] in hosted or node["id"] in kids
        kind = "deploymentNode" if holds or "frame" in node else "infrastructureNode"
        out.open(f"{ids['node:' + node['id']]} = {kind} {_q(node['name'])} {_q('')} {_q(node['technology'])}")
        if node.get("tf"):
            out.open("properties")
            out.add(f'"terraform" {_q(", ".join(node["tf"]))}')
            out.close()
        for child in kids.get(node["id"], []):
            emit(child)
        for container in hosted.get(node["id"], []):
            out.add(f"containerInstance {ids[container]}")
        out.close()

    out.open(f"deploymentEnvironment {_q(deployment['environment'])}")
    for root in kids.get(None, []):
        emit(root)
    out.close()


def _views(out: _Lines, ids: _Ids, model: Model, system: dict) -> None:
    out.open("views")
    for view in c4_views.views(model):
        slug, title = view.slug, _q(view.title)
        if slug == c4_views.CONTEXT:
            out.open(f"systemContext {ids[system['id']]} {_q(slug)} {title}")
        elif slug == c4_views.CONTAINER:
            out.open(f"container {ids[system['id']]} {_q(slug)} {title}")
        elif slug.startswith(c4_views.COMPONENT):
            container = slug.removeprefix(c4_views.COMPONENT + "-")
            out.open(f"component {ids[container]} {_q(slug)} {title}")
        elif slug == c4_views.DEPLOYMENT:
            out.open(f"deployment {ids[system['id']]} {_q(model['deployment']['environment'])} {_q(slug)} {title}")
        elif slug.startswith(c4_views.DYNAMIC):
            out.open(f"dynamic {ids[system['id']]} {_q(slug)} {title}")
            for src, dst, label in _steps(model, system, slug.removeprefix(c4_views.DYNAMIC + "-")):
                out.add(f"{ids[src]} -> {ids[dst]} {_q(label)}")
            out.add("autoLayout lr")
            out.close()
            continue
        else:  # a Code view: Structurizr has no level below components
            continue
        out.add("include *")
        out.add("autoLayout lr")
        out.close()
    out.open("styles")
    for selector, rules in _STYLES:
        out.open(selector)
        for rule in rules:
            out.add(rule)
        out.close()
    out.close()
    out.close()


def workspace(model: Model) -> str:
    """The whole model and its views as one Structurizr DSL workspace."""
    system = in_scope(model)
    by_id = elements(model)
    children: dict[str, list[dict]] = {}
    for element in model["elements"]:
        if element["type"] != "code" and (parent := element.get("parent")):
            children.setdefault(parent, []).append(element)
    ids = _Ids()
    out = _Lines()
    out.open(f"workspace {_q(system['name'])} {_q(system['description'])}")
    out.open("model")
    out.add("!impliedRelationships false")
    for element in model["elements"]:
        if element["type"] in ("person", "system"):
            _element(out, ids, element, children)
    out.add("")
    for r in model["relationships"]:
        if by_id[r["src"]]["type"] == "code" or by_id[r["dst"]]["type"] == "code":
            continue
        props = {"evidence": _evidence(r["evidence"])} | ({"summary": r["summary"]} if r.get("summary") else {})
        _relationship(out, ids, r["src"], r["dst"], r["label"], r.get("technology"), r["dashed"], props)
    for src, dst, text, technology, dashed, behind in rolled_up(model):
        _relationship(out, ids, src, dst, text, technology, dashed, {"rolls up": ", ".join(behind)})
    if "deployment" in model:
        out.add("")
        _deployment(out, ids, model)
    out.close()
    _views(out, ids, model, system)
    out.close()
    return "\n".join(out.lines) + "\n"
