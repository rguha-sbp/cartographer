import pytest

from cartographer import tf_layout
from cartographer.c4_styles import C4
from cartographer.c4_views import views

FACT = [{"fact": "x"}]


def el(eid, kind, parent=None, **extra):
    base = {"id": eid, "type": kind, "name": eid.capitalize(), "description": "Does things", "evidence": FACT}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid, src, dst, label, **extra):
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": False, "evidence": FACT} | extra


def _shop(components=True):
    elements = [
        el("user", "person"),
        el("boss", "person", external=True),
        el("psp", "system", external=True),
        el("shop", "system"),
        el("api", "container", "shop", technology="Python"),
        el("db", "container", "shop", shape="store"),
        el("bus", "container", "shop", shape="queue"),
    ]
    if components:
        elements += [el("auth", "component", "api"), el("cart", "component", "api")]
    rels = [
        rel("r1", "user", "api", "browses", technology="HTTPS", summary="uses shop"),
        rel("r2", "api", "db", "reads", summary="uses db"),
        rel("r3", "api", "psp", "charges"),
        rel("r4", "api", "bus", "publishes", dashed=True),
        rel("r5", "boss", "psp", "audits"),
        rel("r6", "user", "auth" if components else "api", "logs in", summary="uses shop"),
        rel("r7", "cart", "db", "stores carts", summary="uses db"),
        rel("r8", "cart", "auth", "checks"),
    ]
    rels = rels if components else rels[:6]
    scenario = {"id": "buy", "name": "Buy", "steps": ["r1", "r3", "r2"]}
    return {"source": "description", "elements": elements, "relationships": rels, "scenarios": [scenario]}


def _view(model, slug):
    return next(v for v in views(model) if v.slug == slug)


def _ids(items):
    return {i["id"] for i in items}


def test_context_shows_no_containers():
    ctx = _view(_shop(), "1-context").curated
    assert {n["c4"] for n in ctx["nodes"]} == {"system"} and not ctx["groups"]
    assert _ids(ctx["externals"]) == {"user", "psp"}
    assert {e["c4"] for e in ctx["externals"]} == {"person", "system_ext"}


def test_container_view_has_the_system_boundary():
    cv = _view(_shop(), "2-container").curated
    assert cv["groups"] == [{"id": "shop", "label": "Shop\n[Software System]", "kind": "boundary", "parent": None,
                             "column": 0}]
    assert {n["group"] for n in cv["nodes"]} == {"shop"}
    assert {n["c4"] for n in cv["nodes"]} == {"container", "container_store", "container_queue"}
    assert _ids(cv["externals"]) == {"user", "psp"}


def test_nodes_have_the_curated_shape():
    node = next(n for n in _view(_shop(), "2-container").curated["nodes"] if n["id"] == "api")
    assert node["label"] == "Api\n[Container: Python]\nDoes things"
    assert (node["service"], node["tf"], node["multi"]) == ("other", [], False)
    assert node["box"][0] >= 200 and node["box"][1] > 0


def test_component_view_stays_inside_one_container():
    cv = _view(_shop(), "3-component-api").curated
    assert cv["groups"][0]["id"] == "api" and cv["groups"][0]["label"] == "Api\n[Container: Python]"
    assert _ids(cv["nodes"]) == {"auth", "cart"}
    assert _ids(cv["externals"]) == {"user", "db"}
    assert {e["id"]: e["c4"] for e in cv["externals"]}["db"] == "container_store"


def test_views_skip_empty_levels():
    assert [v.slug for v in views(_shop(components=False))] == ["1-context", "2-container", "6-dynamic-buy"]


def test_titles_state_type_and_scope():
    found = {v.slug: v.title for v in views(_shop())}
    assert found["1-context"] == "System Context diagram for Shop"
    assert found["2-container"] == "Container diagram for Shop"
    assert found["3-component-api"] == "Component diagram for Shop: Api"
    assert found["6-dynamic-buy"] == "Dynamic diagram for Shop: Buy"
    assert _view(_shop(), "2-container").curated["title"] == "Container diagram for Shop"


def test_dynamic_numbers_steps_in_order():
    dyn = _view(_shop(), "6-dynamic-buy").curated
    assert [e["label"] for e in dyn["edges"]] == ["1. browses\n[HTTPS]", "2. charges", "3. reads"]
    assert _ids(dyn["nodes"]) == {"api", "db"} and _ids(dyn["externals"]) == {"user", "psp"}


def test_dynamic_keeps_steps_that_share_a_pair():
    model = _shop()
    model["scenarios"] = [{"id": "twice", "name": "Twice", "steps": ["r7", "r2"]}]
    labels = [e["label"] for e in _view(model, "6-dynamic-twice").curated["edges"]]
    assert labels == ["1. stores carts", "2. reads"]


def test_dynamic_maps_steps_to_containers_and_keeps_dashes():
    model = _shop()
    model["scenarios"] = [{"id": "pub", "name": "Pub", "steps": ["r8", "r4"]}]
    edges = _view(model, "6-dynamic-pub").curated["edges"]
    assert [(e["src"], e["dst"], e["dashed"]) for e in edges] == [("api", "bus", True)]


@pytest.mark.parametrize("slug", ["1-context", "2-container", "3-component-api", "6-dynamic-buy"])
def test_every_view_lays_out(slug):
    tf_layout.layout(_view(_shop(), slug).curated, notation=C4)
