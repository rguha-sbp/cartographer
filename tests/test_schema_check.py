import json
from pathlib import Path

import pytest

from cartographer.c4_model import SCHEMA
from cartographer.c4_verify import verify
from cartographer.schema_check import check

FIXTURE = Path(__file__).parent / "fixtures" / "c4" / "model.json"
DEFS = {"thing": {"type": "object", "required": ["id"], "additionalProperties": False,
                  "properties": {"id": {"type": "string", "pattern": "^[a-z]+$"}, "n": {"type": "integer", "minimum": 1}}}}
SCHEMA_ = {"$defs": DEFS, "type": "object", "required": ["things"],
           "properties": {"things": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/thing"}},
                          "kind": {"enum": ["a", "b"]}, "word": {"type": "string", "minLength": 1, "maxLength": 3},
                          "arm": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}}


def _model():
    return json.loads(FIXTURE.read_text())


def test_a_sound_value_has_no_problems():
    assert check({"things": [{"id": "x", "n": 2}], "kind": "a", "word": "abc", "arm": 3}, SCHEMA_) == []


@pytest.mark.parametrize(("value", "problem"), [
    ({}, "model: missing 'things'"),
    ({"things": []}, "things: needs at least 1 item"),
    ({"things": "x"}, "things: must be an array"),
    ({"things": [{"id": "x"}, {}]}, "things[1]: missing 'id'"),
    ({"things": [{"id": "X/.."}]}, "things[0].id: 'X/..' does not match ^[a-z]+$"),
    ({"things": [{"id": "x", "n": 0}]}, "things[0].n: must be at least 1"),
    ({"things": [{"id": "x", "n": True}]}, "things[0].n: must be an integer"),
    ({"things": [{"id": "x", "extra": 1}]}, "things[0]: unknown key 'extra'"),
    ({"things": [{"id": "x"}], "kind": "c"}, "kind: 'c' is not one of 'a', 'b'"),
    ({"things": [{"id": "x"}], "word": ""}, "word: must be at least 1 characters"),
    ({"things": [{"id": "x"}], "word": "abcd"}, "word: must be at most 3 characters"),
    ({"things": [{"id": "x"}], "arm": []}, "arm: matches 0 of its 2 forms, needs exactly one"),
])
def test_each_keyword_reports_a_problem_at_its_path(value, problem):
    assert check(value, SCHEMA_) == [problem]


def test_the_fixture_model_fits_the_c4_schema():
    assert check(_model(), json.loads(SCHEMA.read_text())) == []


def test_malformed_items_are_reported_not_raised(tmp_path):
    m = _model()
    del m["relationships"][3]["dashed"]
    del m["elements"][0]["description"]
    m["relationships"][0]["kind"] = "extends"
    errs = verify(m, None, tmp_path)
    assert "relationships[3]: missing 'dashed'" in errs
    assert "elements[0]: missing 'description'" in errs
    assert "relationships[0].kind: 'extends' is not one of 'uses', 'inherits', 'implements'" in errs


def test_a_wrong_top_level_shape_is_reported_not_raised(tmp_path):
    assert verify({"source": "description", "elements": {}, "relationships": []}, None, tmp_path) == [
        "elements: must be an array"]


def test_empty_evidence_is_a_problem_not_stated(tmp_path):
    m = _model()
    m["elements"][3]["evidence"] = []
    assert "elements[3].evidence: needs at least 1 item" in verify(m, None, tmp_path)


@pytest.mark.parametrize("bad", ["../x", "a/b", "a b", "Api", "-a", ""])
def test_ids_that_would_break_a_file_name_are_problems(tmp_path, bad):
    m = _model()
    m["elements"][3]["id"] = bad
    m["scenarios"][0]["id"] = bad
    m["deployment"]["nodes"][0]["id"] = bad
    errs = verify(m, None, tmp_path)
    for path in ("elements[3].id", "scenarios[0].id", "deployment.nodes[0].id"):
        assert f"{path}: {bad!r} does not match ^[a-z0-9][a-z0-9_-]*$" in errs
