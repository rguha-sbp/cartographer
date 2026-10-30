import copy
from pathlib import Path

import pytest

from cartographer import tf_extract, tf_verify, verify_description

REPO = Path(__file__).parent / "fixtures" / "network"
FACTS = tf_extract.extract(Path("infra"), REPO)
VPC = next(v for v in FACTS["vpcs"] if v["address"] == "aws_vpc.main")
REMOTE = next(v for v in FACTS["vpcs"] if v["remote"])
PLACED = {p["resource"]: p["id"] for p in FACTS["placements"]}


def _group(gid: str, kind: str | None, parent: str | None, **extra: object) -> dict:
    return {"id": gid, "label": gid, "kind": kind, "parent": parent, "column": 0, **extra}


def _node(node_id: str, tf: str, group: str | None) -> dict:
    return {"id": node_id, "tf": [tf], "service": "other", "group": group, "label": node_id}


def _curated(**over: object) -> dict:
    curated = {
        "source": "terraform",
        "title": "t",
        "groups": [
            _group("acct", "account", None),
            _group("vpc", "vpc", "acct", cidrs=VPC["cidrs"], evidence=[{"fact": VPC["id"]}]),
            _group("pub", "subnet", "vpc", tier="public", evidence=[{"fact": PLACED["aws_lb.front"]}]),
            _group("shop", None, "pub"),
        ],
        "nodes": [_node("lb", "aws_lb.front", "shop")],
        "externals": [],
        "edges": [],
        "omitted": [],
    }
    return {**curated, **over}


def _verify(curated: dict) -> tuple[dict, str]:
    return tf_verify.verify(FACTS, curated, REPO)


def _group_of(verified: dict, gid: str) -> dict:
    return next(g for g in verified["groups"] if g["id"] == gid)


def test_a_proven_vpc_and_subnet_tier_pass_untouched() -> None:
    curated = _curated()
    verified, report = _verify(curated)
    assert verified["groups"] == curated["groups"]
    assert verified["nodes"][0]["group"] == "shop"
    assert "Warnings (0)" in report


def test_cidrs_must_equal_the_cited_vpc_fact() -> None:
    curated = _curated()
    curated["groups"][1]["cidrs"] = ["10.30.0.0/16"]
    verified, report = _verify(curated)
    assert "cidrs" not in _group_of(verified, "vpc")
    assert "group vpc: cidrs dropped" in report
    assert tf_verify.needs_attention(curated, verified)


def test_cidrs_without_a_vpc_fact_are_dropped() -> None:
    curated = _curated()
    curated["groups"][1]["evidence"] = [{"fact": PLACED["aws_lb.front"]}]
    assert "cidrs" not in _group_of(_verify(curated)[0], "vpc")


def test_cidr_order_does_not_matter() -> None:
    curated = _curated()
    curated["groups"][1]["cidrs"] = list(reversed(VPC["cidrs"]))
    assert _group_of(_verify(curated)[0], "vpc")["cidrs"] == list(reversed(VPC["cidrs"]))


def test_node_without_placement_of_that_tier_leaves_the_subnet_group() -> None:
    curated = _curated()
    curated["nodes"] = [_node("lb", "aws_lb.front", "shop"), _node("vm", "aws_instance.orders", "shop")]
    verified, report = _verify(curated)
    assert {n["id"]: n["group"] for n in verified["nodes"]} == {"lb": "shop", "vm": "acct"}
    assert "vm: no public placement fact, moved out of subnet group pub" in report
    assert tf_verify.needs_attention(curated, verified)


def test_a_node_directly_in_the_subnet_group_is_checked_too() -> None:
    curated = _curated()
    curated["nodes"] = [_node("vm", "aws_instance.orders", "pub")]
    assert _verify(curated)[0]["nodes"][0]["group"] == "acct"


def test_a_subnet_group_needs_a_vpc_parent() -> None:
    curated = _curated()
    curated["groups"][2]["parent"] = "acct"
    verified, report = _verify(curated)
    assert _group_of(verified, "pub")["kind"] is None
    assert "tier" not in _group_of(verified, "pub")
    assert "group pub: subnet parent acct is not a vpc group" in report
    assert tf_verify.needs_attention(curated, verified)


def test_tier_on_a_plain_group_and_cidrs_on_a_non_vpc_group_are_dropped() -> None:
    curated = _curated()
    curated["groups"][3]["tier"] = "private"
    curated["groups"][0]["cidrs"] = ["10.0.0.0/8"]
    verified, report = _verify(curated)
    assert "tier" not in _group_of(verified, "shop")
    assert "cidrs" not in _group_of(verified, "acct")
    assert "group shop: tier on a group that is not a subnet" in report
    assert "group acct: cidrs on a group that is not a vpc" in report


def test_subnet_group_evidence_must_cite_a_placement_of_its_tier() -> None:
    curated = _curated()
    curated["groups"][2]["evidence"] = [{"fact": PLACED["aws_instance.orders"]}]
    verified, report = _verify(curated)
    assert _group_of(verified, "pub")["kind"] is None
    assert "not a placement with tier public" in report


def test_unknown_or_stated_or_secret_group_evidence_is_rejected() -> None:
    for ev in ({"fact": "p999"}, {"stated": "trust me"}, {"fact": VPC["id"], "x": "password = hunter2hunter2"}):
        curated = _curated()
        curated["groups"][2]["evidence"] = [ev]
        assert _group_of(_verify(curated)[0], "pub")["kind"] is None


def test_a_remote_vpc_fact_cannot_back_cidrs() -> None:
    curated = _curated()
    curated["groups"][1]["evidence"] = [{"fact": REMOTE["id"]}]
    assert "cidrs" not in _group_of(_verify(curated)[0], "vpc")


def test_edges_cannot_cite_network_facts() -> None:
    curated = _curated()
    curated["nodes"].append(_node("vm", "aws_instance.orders", None))
    curated["edges"] = [{"src": "lb", "dst": "vm", "label": "x", "flow": "web", "evidence": [{"fact": VPC["id"]}]}]
    verified, report = _verify(curated)
    assert verified["edges"] == []
    assert "is not an edge fact" in report


def _described(**over: object) -> dict:
    curated = {
        "source": "description",
        "system": "Shop",
        "view": "l7",
        "groups": [
            _group("acct", "account", None),
            _group("vpc", "vpc", "acct", cidrs=["10.0.0.0/16"], evidence=[{"stated": "the VPC is 10.0.0.0/16"}]),
            _group("priv", "subnet", "vpc", tier="private", evidence=[{"stated": "compute is private"}]),
        ],
        "nodes": [{"id": "fn", "label": "fn", "service": "lambda", "group": "priv", "tf": [], "multi": False}],
        "externals": [],
        "edges": [],
    }
    return {**curated, **over}


def test_described_cidrs_and_tier_pass_with_stated_evidence() -> None:
    curated = _described()
    verified, _ = verify_description.verify(curated, Path("."))
    assert verified["groups"] == curated["groups"]


@pytest.mark.parametrize("gid", ["vpc", "priv"])
@pytest.mark.parametrize("evidence", [[], [{"fact": "v1"}]])
def test_described_claims_without_stated_or_file_evidence_are_dropped(gid: str, evidence: list) -> None:
    curated = _described()
    next(g for g in curated["groups"] if g["id"] == gid)["evidence"] = evidence
    verified, report = verify_description.verify(curated, Path("."))
    group = _group_of(verified, gid)
    assert ("cidrs" not in group) if gid == "vpc" else (group["kind"] is None)
    assert "no evidence" in report or "fact evidence is for Terraform diagrams" in report
    assert tf_verify.needs_attention(curated, verified)


def test_described_file_evidence_is_checked(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("vpc 10.0.0.0/16\n")
    curated = _described()
    curated["groups"][1]["evidence"] = [{"file": "plan.md", "line": 1, "contains": "10.0.0.0/16"}]
    assert "cidrs" in _group_of(verify_description.verify(curated, tmp_path)[0], "vpc")
    curated["groups"][1]["evidence"][0]["contains"] = "10.9.9.9"
    assert "cidrs" not in _group_of(verify_description.verify(copy.deepcopy(curated), tmp_path)[0], "vpc")
