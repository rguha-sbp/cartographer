import json
from pathlib import Path

import pytest

from cartographer.c4_verify import verify

FIXTURE = Path(__file__).parent / "fixtures" / "c4" / "model.json"
FN, DATA = "aws_lambda_function.fn", "aws_s3_bucket.data"


def _model():
    return json.loads(FIXTURE.read_text())


def _facts(*extra):
    return {"resources": [{"address": a, "type": a.split(".")[0]} for a in (FN, DATA)],
            "edges": [{"id": "f1", "src": FN, "dst": DATA, "kind": "uses"}], **dict(extra)}


def _nodes(m):
    return m["deployment"]["nodes"]


def _frame(nid, kind, parent=None, **extra):
    node = {"id": nid, "name": nid, "technology": "AWS", "frame": kind, "evidence": [{"stated": "said so"}]}
    return node | ({"parent": parent} if parent else {}) | extra


def test_the_fixture_passes(tmp_path):
    assert verify(_model(), _facts(), tmp_path) == []


def test_a_subnet_frame_needs_a_tier(tmp_path):
    m = _model()
    _nodes(m).append(_frame("net", "subnet"))
    assert verify(m, _facts(), tmp_path) == ["net: a subnet frame needs a tier"]
    _nodes(m)[-1]["tier"] = "private"
    assert verify(m, _facts(), tmp_path) == []


def test_a_node_parenting_itself_is_a_cycle(tmp_path):
    m = _model()
    _nodes(m).append(_frame("vpc", "vpc", "vpc"))
    assert verify(m, _facts(), tmp_path) == ["vpc: parent cycle"]


def test_node_parent_cycles_are_errors_not_hangs(tmp_path):
    m = _model()
    _nodes(m).extend([_frame("a", "vpc", "b"), _frame("b", "account", "a")])
    assert verify(m, _facts(), tmp_path) == ["a: parent cycle", "b: parent cycle"]


@pytest.mark.parametrize("container", ["handler", "analyst", "ghost"])
def test_an_instance_must_place_a_container(tmp_path, container):
    m = _model()
    m["deployment"]["instances"].append({"container": container, "node": "fnnode"})
    assert f"{container}: instance names no container" in verify(m, _facts(), tmp_path)
