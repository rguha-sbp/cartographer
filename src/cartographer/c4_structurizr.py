"""The C4 model as a Structurizr DSL workspace, so one model can also be explored interactively: Structurizr's
viewers drill down from Context to Container to Component, and `structurizr export -format static` turns the
workspace into a static site.

Every view is driven by the matching page of the .drawio, `View.curated`: it includes exactly the page's elements,
and its arrows are the page's edges. The workspace's relationships are therefore those edges, one per ordered pair
and text, not the model's own relationships: each keeps the ids, labels and evidence of the relationships behind it
as properties. Structurizr's implied relationships are off, and a view excludes any relationship between its
elements that its page does not draw. Code views are left out: Structurizr models nothing below a component.
"""

import re
from typing import NamedTuple

from cartographer import c4_views
from cartographer.c4_model import Model, in_scope
from cartographer.c4_views import View

_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_KINDS = {"person": "person", "system": "softwareSystem", "container": "container", "component": "component"}
_STATIC = {c4_views.CONTEXT: "systemContext", c4_views.CONTAINER: "container", c4_views.COMPONENT: "component"}
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
    """A DSL string: quotes and backslashes escaped, line breaks, tabs and other control characters as one space."""
    return '"' + _CONTROL.sub(" ", (text or "").replace("\\", "\\\\").replace('"', '\\"')) + '"'


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
    """DSL identifiers for model, deployment and relationship ids: letters, digits and underscores, unique."""

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


class _Arrow(NamedTuple):
    """A relationship of the workspace: an edge that a page draws. `step` marks one that only a Dynamic page draws."""

    ident: str
    edge: dict
    step: bool


Key = tuple[str, str, str]
STEP_TAG = "Step"


def _key(edge: dict) -> Key:
    return edge["src"], edge["dst"], edge["text"]


def _arrows(views: list[View], ids: _Ids) -> dict[Key, _Arrow]:
    """One relationship for each edge of the pages, by its ends and text: Structurizr allows one relationship per
    ordered pair and description. A pair that several static pages draw (people and external systems on Context and
    Container) lifts the same relationships on each, so it is one. A Dynamic page draws a step with its own label,
    and Structurizr matches a step to a relationship by its ends, description and technology, so a step whose text
    no static page draws for its pair gets a relationship of its own."""
    static = [v for v in views if v.kind in _STATIC]
    dynamic = [v for v in views if v.kind == c4_views.DYNAMIC]
    arrows: dict[Key, _Arrow] = {}
    for step, pages in ((False, static), (True, dynamic)):
        for edge in (edge for view in pages for edge in view.curated["edges"]):
            if _key(edge) not in arrows:
                arrows[_key(edge)] = _Arrow(ids[f"rel:{len(arrows) + 1}"], edge, step)
    return arrows


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


def _relationship(out: _Lines, ids: _Ids, arrow: _Arrow, relationships: dict[str, dict]) -> None:
    edge = arrow.edge
    technology = f" {_q(edge['technology'])}" if edge["technology"] else ""
    out.open(f"{arrow.ident} = {ids[edge['src']]} -> {ids[edge['dst']]} {_q(edge['text'])}{technology}")
    if tags := ["Async"] * edge["dashed"] + [STEP_TAG] * arrow.step:
        out.add("tags " + " ".join(_q(t) for t in tags))
    behind = [relationships[rid] for rid in edge["relationships"]]
    out.open("properties")
    out.add(f'"relationships" {_q(", ".join(edge["relationships"]))}')
    out.add(f'"evidence" {_q(" | ".join(f"{r["label"]}: {_evidence(r["evidence"])}" for r in behind))}')
    out.close()
    out.close()


def _deployment(out: _Lines, ids: _Ids, model: Model) -> None:
    deployment = model["deployment"]
    kids: dict[str | None, list[dict]] = {}
    for node in deployment["nodes"]:
        kids.setdefault(node.get("parent"), []).append(node)
    hosted: dict[str, list[str]] = {}
    for instance in deployment["instances"]:
        hosted.setdefault(instance["node"], []).append(instance["container"])

    def emit(node: dict, root: bool) -> None:
        # Infrastructure that holds nothing is an infrastructureNode, which the DSL allows only inside a
        # deploymentNode: at the root it stays a deploymentNode.
        leaf = node["id"] not in hosted and node["id"] not in kids and "frame" not in node
        kind = "infrastructureNode" if leaf and not root else "deploymentNode"
        out.open(f"{ids['node:' + node['id']]} = {kind} {_q(node['name'])} {_q('')} {_q(node['technology'])}")
        if node.get("tf"):
            out.open("properties")
            out.add(f'"terraform" {_q(", ".join(node["tf"]))}')
            out.close()
        for child in kids.get(node["id"], []):
            emit(child, False)
        for container in hosted.get(node["id"], []):
            out.add(f"containerInstance {ids[container]}")
        out.close()

    out.open(f"deploymentEnvironment {_q(deployment['environment'])}")
    for root in kids.get(None, []):
        emit(root, True)
    out.close()


def _static(out: _Lines, ids: _Ids, view: View, arrows: dict[Key, _Arrow]) -> None:
    """A Context, Container or Component view of exactly the page's elements and edges."""
    curated = view.curated
    shown = [n["id"] for n in curated["nodes"]] + [e["id"] for e in curated["externals"]]
    drawn = {_key(edge) for edge in curated["edges"]}
    hidden = [arrow.ident for key, arrow in arrows.items()
              if key[0] in shown and key[1] in shown and key not in drawn]
    out.open(f"{_STATIC[view.kind]} {ids[view.subject]} {_q(view.slug)}")
    out.add(f"title {_q(view.title)}")
    if shown:
        out.add("include " + " ".join(ids[eid] for eid in shown))
    if hidden:
        out.add("exclude " + " ".join(hidden))
    out.add("autoLayout lr")
    out.close()


def _dynamic(out: _Lines, ids: _Ids, view: View, system: dict, arrows: dict[Key, _Arrow]) -> None:
    """The page's steps, each with its number in the scenario and its own label. The technology is that of the
    relationship the step names, which is the step's own unless a static page draws the same text over more."""
    # Scoped to the system, a Dynamic view shows its containers; one without a boundary is at Context level and
    # shows the system itself, which only the unscoped view may.
    scope = ids[system["id"]] if view.curated["groups"] else "*"
    out.open(f"dynamic {scope} {_q(view.slug)}")
    out.add(f"title {_q(view.title)}")
    for edge in view.curated["edges"]:
        technology = arrows[_key(edge)].edge["technology"]
        technology = f" {_q(technology)}" if technology else ""
        out.add(f"{edge['step']}: {ids[edge['src']]} -> {ids[edge['dst']]} {_q(edge['text'])}{technology}")
    out.add("autoLayout lr")
    out.close()


def _views(out: _Lines, ids: _Ids, model: Model, views: list[View], arrows: dict[Key, _Arrow]) -> None:
    system = in_scope(model)
    out.open("views")
    for view in views:
        if view.kind in _STATIC:
            _static(out, ids, view, arrows)
        elif view.kind == c4_views.DYNAMIC:
            _dynamic(out, ids, view, system, arrows)
        elif view.kind == c4_views.DEPLOYMENT:
            # Structurizr gives container instances the relationships of their containers. Without the Dynamic
            # steps' own relationships those are the Container page's edges: the same arrows as the Deployment page.
            out.open(f"deployment {ids[system['id']]} {_q(model['deployment']['environment'])} {_q(view.slug)}")
            out.add(f"title {_q(view.title)}")
            out.add("include *")
            out.add(f'exclude "relationship.tag=={STEP_TAG}"')
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
    views = [v for v in c4_views.views(model) if v.kind != c4_views.CODE]
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
    arrows = _arrows(views, ids)
    relationships = {r["id"]: r for r in model["relationships"]}
    out.add("")
    for arrow in arrows.values():
        _relationship(out, ids, arrow, relationships)
    if "deployment" in model:
        out.add("")
        _deployment(out, ids, model)
    out.close()
    _views(out, ids, model, views, arrows)
    out.close()
    return "\n".join(out.lines) + "\n"
