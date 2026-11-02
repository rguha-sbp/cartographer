import copy
import json
from pathlib import Path

from stub_cloud import StubCloud

from cartographer import gen_drawio, notation, tf_layout, tfdiagram, verify_description
from cartographer.clouds import CLOUDS
from cartographer.curated_format import upgrade
from cartographer.tf_externals import adopt
from cartographer.verify_shared import shape_warnings

F1 = {"view": "l7", "source": "description", "system": "S",
      "groups": [{"id": "v", "label": "VPC", "kind": "vpc", "parent": None, "column": 0, "cidrs": ["10.0.0.0/16"]},
                 {"id": "app", "label": "App", "kind": None, "parent": "v", "column": 0}],
      "nodes": [{"id": "fn", "label": "fn", "service": "lambda", "group": "app", "tf": [], "multi": False},
                {"id": "box", "label": "box", "service": "other", "icon": "users", "group": None, "tf": [],
                 "multi": False},
                {"id": "plain", "label": "plain", "service": "other", "group": None, "tf": [], "multi": False},
                {"id": "blank", "label": "blank", "service": "lambda", "icon": "none", "group": None, "tf": [],
                 "multi": False}],
      "externals": [{"id": "ddb", "label": "t", "icon": "none", "service": "dynamodb", "evidence": []},
                    {"id": "gh", "label": "gh", "icon": "github", "evidence": []},
                    {"id": "nil", "label": "nil", "icon": "none", "evidence": []}],
      "edges": []}


def test_upgrade_converts_a_format_1_file() -> None:
    old = copy.deepcopy(F1)
    new = upgrade(old)
    assert old == F1
    assert new["format"] == 2
    assert new["groups"][0] == {**F1["groups"][0], "kind": "network", "cloud": "aws"}
    assert new["groups"][1] == F1["groups"][1]
    assert [n.get("icon") for n in new["nodes"]] == ["aws:lambda", "generic:users", None, None]
    assert [x.get("icon") for x in new["externals"]] == ["aws:dynamodb", "brand:github", "none"]
    assert "service" not in json.dumps(new)


def test_upgrade_leaves_format_2_alone() -> None:
    f2 = upgrade(F1)
    assert upgrade(f2) is f2


def test_schema_has_no_injected_enum() -> None:
    text = tfdiagram.schema_text()
    assert "lambda" not in text and "aws_icons" not in text


def test_a_legacy_file_still_verifies_and_lays_out() -> None:
    verified, _ = verify_description.verify(upgrade(F1), Path("."))
    xml = gen_drawio.render(tf_layout.layout({**verified, "title": "T"}), page_id="p", page_name="p")
    assert "resIcon=mxgraph.aws4.lambda;" in xml and "grIcon=mxgraph.aws4.group_vpc2;" in xml


def _stub_cloud(monkeypatch) -> None:
    aws = CLOUDS["aws"]
    stub = StubCloud("stub", "Stub", ("stub",), {"vm": {"fill": "#000000", "title": "VM"}}, aws.frame_styles,
                 "Stub managed services")
    monkeypatch.setitem(CLOUDS, "stub", stub)


def _aws_frames() -> list[dict]:
    return [{"id": "g_cloud", "label": "AWS", "kind": "cloud", "cloud": "aws", "parent": None, "column": 0},
            {"id": "g_region", "label": "r", "kind": "region", "cloud": "aws", "parent": "g_cloud", "column": 0}]


def test_managed_external_of_a_cloud_without_region_gets_its_own_cloud_frame(monkeypatch) -> None:
    _stub_cloud(monkeypatch)
    externals = [{"id": "vm", "label": "VM", "icon": "stub:vm", "evidence": []},
                 {"id": "ddb", "label": "T", "icon": "aws:dynamodb", "evidence": []},
                 {"id": "gh", "label": "gh", "icon": "brand:github", "evidence": []}]
    out = adopt({"groups": _aws_frames(), "nodes": [], "externals": externals, "edges": []})
    groups = {g["id"]: g for g in out["groups"]}
    assert groups["g_stub_cloud"] == {"id": "g_stub_cloud", "label": "Stub", "kind": "cloud", "cloud": "stub",
                                      "parent": None, "column": None}
    assert groups["g_stub_managed"]["parent"] == "g_stub_cloud"
    assert groups["g_stub_managed"]["label"] == "Stub managed services"
    assert groups["g_aws_managed"]["parent"] == "g_region" and "g_aws_cloud" not in groups
    assert {n["id"]: (n["group"], n["icon"]) for n in out["nodes"]} == {
        "vm": ("g_stub_managed", "stub:vm"), "ddb": ("g_aws_managed", "aws:dynamodb")}
    assert [x["id"] for x in out["externals"]] == ["gh"]


def test_a_frame_without_a_known_cloud_becomes_a_plain_group() -> None:
    curated = upgrade(F1)
    del curated["groups"][0]["cloud"]
    verified, report = verify_description.verify(curated, Path("."))
    assert verified["groups"][0]["kind"] is None and "without a known cloud" in report
    assert "cidrs" not in verified["groups"][0]


def test_shape_warnings_name_an_unknown_icon() -> None:
    assert shape_warnings({"id": "a", "icon": "aws:lambda"}) == []
    assert shape_warnings({"id": "a", "icon": "none"}) == []
    assert shape_warnings({"id": "a"}) == []
    assert shape_warnings({"id": "a", "icon": "aws:nope"}) == ["a: icon 'aws:nope' is not a known icon, renders as a box"]


def test_a_frame_without_a_known_cloud_fails_to_render_with_a_clear_error() -> None:
    import pytest

    from cartographer.diagram_model import Group

    with pytest.raises(ValueError, match="group g_x.*cloud None"):
        notation.cloud_group(Group("g_x", "X", 0, 0, 10, 10, kind="region"))
    with pytest.raises(ValueError, match="group g_x.*cloud 'nope'"):
        notation.cloud_group(Group("g_x", "X", 0, 0, 10, 10, kind="region", cloud="nope"))


def test_upgrade_rejects_an_unknown_format() -> None:
    import pytest

    with pytest.raises(ValueError, match="format 3"):
        upgrade({**F1, "format": 3})
