import json
from pathlib import Path

from cartographer import overrides
from cartographer.overrides import Override

FACTS = {"resources": [
    {"address": "aws_s3_bucket.a", "type": "aws_s3_bucket"},
    {"address": "aws_s3_bucket.b", "type": "aws_s3_bucket"},
]}


def _verified() -> dict:
    node = {"group": None, "multi": False, "icon": "aws:s3", "decided_by": "catalog aws_s3_bucket", "marked": False}
    return {"nodes": [{**node, "id": "a", "tf": ["aws_s3_bucket.a"]}, {**node, "id": "b", "tf": ["aws_s3_bucket.b"]}],
            "externals": []}


def test_bad_override_file_is_reported_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "icons.json"
    assert overrides.load(path) == ([], [])
    path.write_text("{not json")
    assert overrides.load(path)[0] == []
    assert "icons.json" in overrides.load(path)[1][0]
    good = {"cloud": "aws", "type": "aws_s3_bucket", "icon": "s3", "reason": "why"}
    path.write_text(json.dumps({"overrides": [good, {**good, "reason": ""}, {"cloud": "aws"}]}))
    loaded, problems = overrides.load(path)
    assert loaded == [Override("aws", "aws_s3_bucket", "s3", "why", None)]
    assert [p.split(":")[0] for p in problems] == ["override 1", "override 2"]


def test_unknown_icon_and_address_are_refused_and_the_rest_applies() -> None:
    verified = _verified()
    lines = overrides.apply(verified, FACTS, [
        Override("aws", "aws_s3_bucket", "no_such_icon", "r", None),
        Override("aws", "aws_s3_bucket", "lambda", "r", "aws_s3_bucket.nope"),
        Override("aws", "aws_s3_bucket", "lambda", "good", "aws_s3_bucket.a"),
    ])
    assert verified["nodes"][0]["icon"] == "aws:lambda" and verified["nodes"][1]["icon"] == "aws:s3"
    assert sum("refused" in line for line in lines) == 2 and sum("applied" in line for line in lines) == 1


def test_address_override_beats_type_override() -> None:
    verified = _verified()
    overrides.apply(verified, FACTS, [
        Override("aws", "aws_s3_bucket", "lambda", "by address", "aws_s3_bucket.a"),
        Override("aws", "aws_s3_bucket", "sqs", "by type", None),
    ])
    a, b = verified["nodes"]
    assert (a["icon"], a["override"], a["decided_by"]) == ("aws:lambda", "by address", "override")
    assert (b["icon"], b["override"]) == ("aws:sqs", "by type")


def test_described_diagram_takes_type_wide_overrides_on_tf_type() -> None:
    verified = {"nodes": [{"id": "x", "tf": [], "tf_type": "aws_s3_bucket", "icon": "aws:s3"}], "externals": []}
    lines = overrides.apply(verified, None, [Override("aws", "aws_s3_bucket", "lambda", "r", None),
                                             Override("aws", "aws_s3_bucket", "sqs", "r", "aws_s3_bucket.a")])
    assert verified["nodes"][0]["icon"] == "aws:lambda"
    assert any("refused" in line for line in lines)


def test_an_address_override_skips_externals_that_carry_no_tf() -> None:
    verified = _verified()
    verified["externals"] = [{"id": "ext", "label": "outside", "icon": "generic:users"}]
    lines = overrides.apply(verified, FACTS, [Override("aws", "aws_s3_bucket", "lambda", "why", "aws_s3_bucket.a")])
    assert verified["nodes"][0]["icon"] == "aws:lambda" and verified["externals"][0]["icon"] == "generic:users"
    assert lines[0].startswith("applied")
