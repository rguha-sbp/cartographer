import json

import pytest

from cartographer.c4_model import (
    SCHEMA,
    RollupError,
    ancestors,
    edge_text,
    elements,
    in_scope,
    rollup,
    type_line,
    visible,
)

FACT = [{"fact": "x"}]


def el(eid, kind, parent=None, **extra):
    base = {"id": eid, "type": kind, "name": eid, "description": "d", "evidence": FACT}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid, src, dst, label, dashed=False, **extra):
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": dashed, "evidence": FACT} | extra


def _model(rels):
    return {
        "source": "description",
        "elements": [
            el("u", "person"),
            el("ext", "system", external=True),
            el("s", "system"),
            el("a", "container", "s"),
            el("b", "container", "s"),
            el("a1", "component", "a"),
            el("a2", "component", "a"),
            el("b1", "component", "b"),
        ],
        "relationships": rels,
    }


def test_rollup_lifts_component_relationships_to_containers():
    m = _model([rel("r1", "a1", "b1", "reads orders")])
    assert rollup(m, {"a", "b"}) == [{"src": "a", "dst": "b", "label": "reads orders", "dashed": False,
                                      "relationships": ["r1"]}]


def test_rollup_names_the_relationships_behind_each_edge():
    m = _model([rel("r2", "a2", "b1", "reads"), rel("r1", "a1", "b1", "reads")])
    assert rollup(m, {"a", "b"})[0]["relationships"] == ["r1", "r2"]


def test_rollup_drops_relationships_inside_one_visible_element():
    assert rollup(_model([rel("r1", "a1", "a2", "calls")]), {"a", "b"}) == []


def test_rollup_drops_relationships_with_an_end_that_is_not_shown():
    assert rollup(_model([rel("r1", "u", "a1", "uses")]), {"a", "b"}) == []


def test_rollup_uses_shared_summary_for_several_relationships():
    m = _model([rel("r1", "a1", "b1", "reads", summary="uses orders"), rel("r2", "a2", "b1", "writes", summary="uses orders")])
    assert rollup(m, {"a", "b"})[0]["label"] == "uses orders"


def test_rollup_summary_carries_the_shared_technology():
    m = _model([rel("r1", "a1", "b1", "reads", summary="uses orders", technology="SQL"),
                rel("r2", "a2", "b1", "writes", summary="uses orders", technology="SQL")])
    assert rollup(m, {"a", "b"})[0]["label"] == "uses orders\n[SQL]"


def test_rollup_summary_over_different_technologies_fails():
    m = _model([rel("r1", "a1", "b1", "reads", summary="uses orders", technology="SQL"),
                rel("r2", "a2", "b1", "writes", summary="uses orders", technology="HTTPS")])
    with pytest.raises(RollupError, match="a->b: relationships r1, r2 need a shared summary and technology"):
        rollup(m, {"a", "b"})


def test_rollup_merges_identical_relationships():
    m = _model([rel("r1", "a1", "b1", "reads"), rel("r2", "a2", "b1", "reads")])
    assert rollup(m, {"a", "b"})[0]["label"] == "reads"


def test_rollup_conflict_names_both_relationships():
    m = _model([rel("r1", "a1", "b1", "reads"), rel("r2", "a2", "b1", "writes")])
    with pytest.raises(RollupError) as err:
        rollup(m, {"a", "b"})
    assert err.value.pair == ("a", "b") and err.value.relationships == ["r1", "r2"]


def test_rollup_is_dashed_only_when_every_part_is():
    m = _model([rel("r1", "a1", "b1", "x", dashed=True, summary="s"), rel("r2", "a2", "b1", "y", summary="s")])
    assert rollup(m, {"a", "b"})[0]["dashed"] is False


def test_rollup_label_carries_technology_on_its_own_line():
    m = _model([rel("r1", "a", "b", "reads orders", technology="HTTPS")])
    assert rollup(m, {"a", "b"})[0]["label"] == "reads orders\n[HTTPS]"


def test_rollup_is_sorted_by_ends():
    m = _model([rel("r1", "b", "a", "x"), rel("r2", "a", "b", "y")])
    assert [(e["src"], e["dst"]) for e in rollup(m, {"a", "b"})] == [("a", "b"), ("b", "a")]


def test_ancestors_and_visible():
    m = _model([])
    assert ancestors(m, "a1") == ["a", "s"]
    assert ancestors(m, "s") == []
    assert visible(m, "a1", {"a", "s"}) == "a"
    assert visible(m, "a", {"a"}) == "a"
    assert visible(m, "u", {"a"}) is None


def test_elements_and_in_scope():
    m = _model([])
    assert elements(m)["a"]["parent"] == "s"
    assert in_scope(m)["id"] == "s"


def test_type_lines():
    assert type_line({"type": "container", "technology": "Python, AWS Lambda"}) == "[Container: Python, AWS Lambda]"
    assert type_line({"type": "person"}) == "[Person]"
    assert type_line({"type": "system", "external": True}) == "[Software System]"
    assert type_line({"type": "code", "stereotype": "interface"}) == "<<interface>>"


def test_edge_text():
    assert edge_text("reads", None) == "reads"
    assert edge_text("reads", "HTTPS") == "reads\n[HTTPS]"


def test_schema_is_valid_json_with_the_element_types():
    schema = json.loads(SCHEMA.read_text())
    assert schema["$defs"]["element"]["properties"]["type"]["enum"] == ["person", "system", "container", "component", "code"]
