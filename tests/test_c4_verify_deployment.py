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
    node = {"id": nid, "name": nid, "technology": "AWS", "frame": kind, "cloud": "aws",
            "evidence": [{"stated": "said so"}]}
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
    _nodes(m).append(_frame("vpc", "network", "vpc"))
    assert verify(m, _facts(), tmp_path) == ["vpc: parent cycle"]


def test_node_parent_cycles_are_errors_not_hangs(tmp_path):
    m = _model()
    _nodes(m).extend([_frame("a", "network", "b"), _frame("b", "account", "a")])
    assert verify(m, _facts(), tmp_path) == ["a: parent cycle", "b: parent cycle"]


@pytest.mark.parametrize("container", ["handler", "analyst", "ghost"])
def test_an_instance_must_place_a_container(tmp_path, container):
    m = _model()
    m["deployment"]["instances"].append({"container": container, "node": "fnnode"})
    assert f"{container}: instance names no container" in verify(m, _facts(), tmp_path)


def test_a_node_fact_must_touch_its_own_addresses(tmp_path):
    m = _model()
    _nodes(m)[1]["evidence"] = [{"fact": "f2"}]
    elsewhere = _facts(("edges", [*_facts()["edges"], {"id": "f2", "src": FN, "dst": "aws_sqs_queue.q", "kind": "uses"}]))
    assert verify(m, elsewhere, tmp_path) == ["bucket: fact f2 does not join the deployment nodes hosting it"]


@pytest.mark.parametrize("cloud", ["aws", "azure", None, "nope"])
def test_a_frame_needs_a_known_cloud(tmp_path, cloud):
    m = _model()
    _nodes(m).append({k: v for k, v in (_frame("net", "region") | {"cloud": cloud}).items() if v is not None})
    assert verify(m, _facts(), tmp_path) == ([] if cloud in ("aws", "azure") else ["net: a frame needs a known cloud"])


def test_a_frame_may_cite_its_network_fact(tmp_path):
    m = _model()
    _nodes(m).append(_frame("vpc", "network", tf=["aws_vpc.main"]) | {"evidence": [{"fact": "v1"}]})
    facts = _facts(("networks", [{"id": "v1", "address": "aws_vpc.main", "name": "main"}]))
    facts["resources"].append({"address": "aws_vpc.main", "type": "aws_vpc"})
    assert verify(m, facts, tmp_path) == []


@pytest.mark.parametrize(("resource", "ok"), [(FN, True), ("aws_lambda_function.other", False)])
def test_an_element_may_cite_a_placement_of_its_hosts(tmp_path, resource, ok):
    m = _model()
    m["elements"][3]["evidence"] = [{"fact": "p1"}]
    facts = _facts(("placements", [{"id": "p1", "resource": resource, "network": "v1", "tier": "private"}]))
    assert verify(m, facts, tmp_path) == ([] if ok else ["fn: fact p1 does not join the deployment nodes hosting it"])
