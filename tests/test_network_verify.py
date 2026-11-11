import copy
from pathlib import Path

import pytest

from cartographer import tf_extract, tf_verify, verify_description
from cartographer.curated_format import FRAME_KINDS
from cartographer.verify_shared import cloud_warnings

REPO = Path(__file__).parent / "fixtures" / "network"
FACTS = tf_extract.extract(Path("infra"), REPO)
VPC = next(v for v in FACTS["networks"] if v["address"] == "aws_vpc.main")
REMOTE = next(v for v in FACTS["networks"] if v["remote"])
PLACED = {p["resource"]: p["id"] for p in FACTS["placements"]}


def _group(gid: str, kind: str | None, parent: str | None, **extra: object) -> dict:
    cloud = {"cloud": "aws"} if kind in FRAME_KINDS else {}
    return {"id": gid, "label": gid, "kind": kind, "parent": parent, "column": 0, **cloud, **extra}


def _node(node_id: str, tf: str, group: str | None) -> dict:
    return {"id": node_id, "tf": [tf], "group": group, "label": node_id}


def _curated(**over: object) -> dict:
    curated = {
        "format": 2,
        "source": "terraform",
        "title": "t",
        "groups": [
            _group("acct", "account", None),
            _group("vpc", "network", "acct", cidrs=VPC["cidrs"], evidence=[{"fact": VPC["id"]}]),
            _group("pub", "subnet", "vpc", tier="public", evidence=[{"fact": PLACED["aws_lb.front"]}]),
            _group("shop", None, "pub"),
        ],
        "nodes": [_node("lb", "aws_lb.front", "shop")],
        "externals": [],
        "edges": [],
        "omitted": [],
    }
    return {**curated, **over}


def _verify(curated: dict, facts: dict = FACTS) -> tuple[dict, str]:
    return tf_verify.verify(facts, curated, REPO)


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
    assert {n["id"]: n["group"] for n in verified["nodes"]} == {"lb": "shop", "vm": "vpc"}
    assert "vm: no public placement fact, moved out of subnet group pub" in report
    assert "drawn outside any network group" not in report
    assert tf_verify.needs_attention(curated, verified)


def test_a_node_directly_in_the_subnet_group_is_checked_too() -> None:
    curated = _curated()
    curated["nodes"] = [_node("vm", "aws_instance.orders", "pub")]
    assert _verify(curated)[0]["nodes"][0]["group"] == "vpc"


def test_a_subnet_group_needs_a_vpc_parent() -> None:
    curated = _curated()
    curated["groups"][2]["parent"] = "acct"
    verified, report = _verify(curated)
    assert _group_of(verified, "pub")["kind"] is None
    assert "tier" not in _group_of(verified, "pub")
    assert "group pub: subnet parent acct is not a network group" in report
    assert tf_verify.needs_attention(curated, verified)


def test_tier_on_a_plain_group_and_cidrs_on_a_non_vpc_group_are_dropped() -> None:
    curated = _curated()
    curated["groups"][3]["tier"] = "private"
    curated["groups"][0]["cidrs"] = ["10.0.0.0/8"]
    verified, report = _verify(curated)
    assert "tier" not in _group_of(verified, "shop")
    assert "cidrs" not in _group_of(verified, "acct")
    assert "group shop: tier on a group that is not a subnet" in report
    assert "group acct: cidrs on a group that is not a network" in report


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


def test_a_network_group_keeps_only_evidence_that_cites_a_network_fact_or_code() -> None:
    bad = [{"fact": "n999"}, {"fact": PLACED["aws_lb.front"]}, {"stated": "trust me"}, {"file": "nope.tf", "line": 1, "contains": "x"}]
    for cidrs in ({"cidrs": VPC["cidrs"]}, {}):
        curated = _curated()
        curated["groups"][1] = _group("vpc", "network", "acct", **cidrs, evidence=[{"fact": VPC["id"]}, *bad])
        verified, report = _verify(curated)
        assert _group_of(verified, "vpc") == {**curated["groups"][1], "evidence": [{"fact": VPC["id"]}]}
        assert "group vpc: evidence dropped, " in report


def test_edges_cannot_cite_network_facts() -> None:
    curated = _curated()
    curated["nodes"].append(_node("vm", "aws_instance.orders", None))
    curated["edges"] = [{"src": "lb", "dst": "vm", "label": "x", "flow": "web", "evidence": [{"fact": VPC["id"]}]}]
    verified, report = _verify(curated)
    assert verified["edges"] == []
    assert "is not an edge fact" in report


SHARED_FN = "module.worker.aws_lambda_function.fn"
LOCAL_VM = "aws_instance.orders"
SG = "module.worker.aws_security_group.sg"


def _boxes(shared_nodes: list[dict], *extra_nodes: dict, **shared: object) -> dict:
    """The local VPC `vpc` with its own nodes, and a network group `shared` citing the remote VPC, in one account."""
    return _curated(
        groups=[
            _group("acct", "account", None),
            _group("vpc", "network", "acct", cidrs=VPC["cidrs"], evidence=[{"fact": VPC["id"]}]),
            _group("shared", "network", "acct", **{"evidence": [{"fact": REMOTE["id"]}], **shared}),
        ],
        nodes=[_node("lb", "aws_lb.front", "vpc"), *shared_nodes, *extra_nodes],
    )


def _placement(resource: str, network: str) -> dict:
    return {"id": f"p-{resource}-{network}", "resource": resource, "network": network, "tier": "private", "via": "x",
            "file": "infra/main.tf", "line": 1}


EXTERNAL = (_node("fn", SHARED_FN, "shared"),)
MOVED_VM = "vm: placed in main, not in network group shared; moved out"
MOVED_FN = "fn: placed in shared-vpc, not in network group vpc; moved out"


@pytest.mark.parametrize(("nodes", "extra", "group_of", "external", "note"), [
    (EXTERNAL, [], {"fn": "shared"}, True, None),
    ((_node("fn", SHARED_FN, "shared"), _node("vm", LOCAL_VM, "shared")), [], {"fn": "shared", "vm": "acct"}, True, MOVED_VM),
    ((_node("vm", LOCAL_VM, "shared"),), [], {"vm": "acct"}, False, MOVED_VM),  # emptied: no marker
    ((_node("fn", SHARED_FN, "vpc"),), [], {"fn": "acct"}, False, MOVED_FN),
    ((_node("sg", SG, "vpc"),), [], {"sg": "vpc"}, False, None),  # no placement fact: not checked
    ((_node("sg", SG, "shared"),), [], {"sg": "shared"}, True, None),
    ((_node("fn", SHARED_FN, "acct"),), [], {"fn": "acct"}, False, "fn: placed in shared-vpc, drawn outside any network group"),
    ((_node("fn", SHARED_FN, "vpc"),), [_placement(SHARED_FN, VPC["id"])], {"fn": "vpc"}, False, None),  # runs in both
])
def test_correct_box(nodes: tuple, extra: list, group_of: dict, external: bool, note: str | None) -> None:
    curated = _boxes(list(nodes))
    verified, report = _verify(curated, {**FACTS, "placements": [*FACTS["placements"], *extra]})
    assert {n["id"]: n["group"] for n in verified["nodes"] if n["id"] != "lb"} == group_of
    assert _group_of(verified, "shared").get("external", False) is external
    assert "external" not in _group_of(verified, "vpc")
    assert note is None or note in report
    assert ("moved out" in report) is (note is not None and "moved out" in note)
    if note and "moved out" in note:
        assert tf_verify.needs_attention(curated, verified)  # a node left a box it was drawn in


def test_a_group_citing_a_local_and_a_remote_network_is_not_external() -> None:
    verified, report = _verify(_boxes(list(EXTERNAL), evidence=[{"fact": REMOTE["id"]}, {"fact": VPC["id"]}]))
    assert "external" not in _group_of(verified, "shared")
    assert f"group shared: cites 2 network facts ({', '.join(sorted([REMOTE['id'], VPC['id']]))})" in report


def test_a_group_that_cites_no_network_is_noted_and_its_nodes_are_not_checked() -> None:
    verified, report = _verify(_boxes([_node("vm", LOCAL_VM, "shared")], evidence=[]))
    assert "group shared: cites no network fact, its nodes cannot be checked" in report
    assert next(n for n in verified["nodes"] if n["id"] == "vm")["group"] == "shared"
    assert "external" not in _group_of(verified, "shared")


def test_wrong_cidrs_drop_but_the_group_still_stands_for_its_network() -> None:
    _, report = _verify(_boxes([_node("vm", LOCAL_VM, "shared")], cidrs=["10.9.0.0/16"]))
    assert "group shared: cidrs dropped" in report
    assert MOVED_VM in report


def test_a_cited_network_survives_a_cidrs_claim_another_fact_backs() -> None:
    verified, _ = _verify(_boxes(list(EXTERNAL), cidrs=VPC["cidrs"], evidence=[{"fact": VPC["id"]}, {"fact": REMOTE["id"]}]))
    assert _group_of(verified, "shared")["cidrs"] == VPC["cidrs"]
    assert {ev["fact"] for ev in _group_of(verified, "shared")["evidence"]} == {VPC["id"], REMOTE["id"]}


def test_a_curated_external_is_dropped_and_set_by_the_tool() -> None:
    curated = _boxes(list(EXTERNAL), external=False)
    _group_of(curated, "vpc")["external"] = True
    verified, report = _verify(curated)
    assert _group_of(verified, "shared")["external"] is True
    assert "external" not in _group_of(verified, "vpc")
    assert "group vpc: external is set by verify, not the curator, dropped" in report


def test_a_vpc_the_stack_creates_gets_no_marker_and_no_warning() -> None:
    verified, report = _verify(_curated())
    assert "external" not in _group_of(verified, "vpc")
    assert "Warnings (0)" in report




def _described(**over: object) -> dict:
    curated = {
        "format": 2,
        "source": "description",
        "system": "Shop",
        "view": "l7",
        "groups": [
            _group("acct", "account", None),
            _group("vpc", "network", "acct", cidrs=["10.0.0.0/16"], evidence=[{"stated": "the VPC is 10.0.0.0/16"}]),
            _group("priv", "subnet", "vpc", tier="private", evidence=[{"stated": "compute is private"}]),
        ],
        "nodes": [{"id": "fn", "label": "fn", "icon": "aws:lambda", "group": "priv", "tf": [], "multi": False}],
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


BARE = ("address", "type", "module", "multi", "file", "line")


def _facts_with(**resolutions: dict) -> dict:
    """The facts with every resource's resolution removed, and the given one (by address with `.` as `__`) set."""
    chosen = {k.replace("__", "."): v for k, v in resolutions.items()}
    resources = [{**{k: r[k] for k in BARE}, **chosen.get(r["address"], {})} for r in FACTS["resources"]]
    return {**FACTS, "resources": resources}


LB = {"icon": "aws:ec2", "decided_by": "catalog aws_lb", "marked": True}
MISC = "aws_instance.misc"


def test_verify_takes_the_icon_from_the_first_resolved_address() -> None:
    facts = _facts_with(aws_lb__front=LB, aws_instance__orders={"icon": "aws:lambda", "marked": False})
    curated = _curated()
    curated["nodes"] = [{**_node("n", "aws_lb.front", "shop"), "tf": [MISC, "aws_lb.front", "aws_instance.orders"],
                         "icon": "generic:users"}]
    verified, report = tf_verify.verify(facts, curated, REPO)
    node = verified["nodes"][0]
    assert (node["icon"], node["decided_by"], node["marked"]) == ("aws:ec2", "catalog aws_lb", True)
    assert "n: curator icon is set but the resources resolve, resolved icon wins" in report


def test_verify_sets_no_warning_when_the_curator_left_the_icon_to_the_facts() -> None:
    verified, report = tf_verify.verify(_facts_with(aws_lb__front=LB), _curated(), REPO)
    assert verified["nodes"][0]["icon"] == "aws:ec2" and "Warnings (0)" in report


def test_verify_keeps_the_curator_icon_when_nothing_resolves() -> None:
    curated = _curated()
    curated["nodes"] = [{**_node("n", MISC, "shop"), "icon": "aws:lambda"}]
    node = tf_verify.verify(_facts_with(), curated, REPO)[0]["nodes"][0]
    assert (node["icon"], node["decided_by"], node["marked"]) == ("aws:lambda", "curator", True)


def test_verify_warns_on_a_node_built_only_from_folds() -> None:
    curated = _curated()
    curated["nodes"] = [_node("n", MISC, "shop")]
    report = tf_verify.verify(_facts_with(aws_instance__misc={"fold": "owner"}), curated, REPO)[1]
    assert "n: built only from folded resources" in report


def test_a_node_icon_of_another_cloud_than_its_frame_is_a_warning() -> None:
    frame = {"id": "f", "label": "f", "kind": "region", "cloud": "azure", "parent": None, "column": 0}
    diagram = {"groups": [frame, {**frame, "id": "g", "kind": None, "parent": "f"}],
               "nodes": [{"id": "n", "group": "g", "icon": "aws:lambda"}, {"id": "m", "group": "g", "icon": "brand:github"}], "externals": []}
    assert cloud_warnings(diagram) == ["n: icon aws:lambda belongs to aws, its frame to azure"]


def test_verify_prefers_a_service_icon_over_a_generic_one() -> None:
    facts = _facts_with(aws_lb__front=LB, aws_instance__misc={"icon": "generic:folder", "marked": False})
    curated = _curated()
    curated["nodes"] = [{**_node("n", MISC, "shop"), "tf": [MISC, "aws_lb.front"]}]
    assert tf_verify.verify(facts, curated, REPO)[0]["nodes"][0]["icon"] == "aws:ec2"


def test_an_external_icon_of_another_cloud_than_its_frame_is_a_warning() -> None:
    frame = {"id": "f", "label": "f", "kind": "region", "cloud": "azure", "parent": None, "column": 0}
    diagram = {"groups": [frame], "nodes": [],
               "externals": [{"id": "x", "group": "f", "icon": "aws:lambda"}, {"id": "y", "group": None, "icon": "aws:lambda"}]}
    assert cloud_warnings(diagram) == ["x: icon aws:lambda belongs to aws, its frame to azure"]


def test_described_mode_drops_a_curated_external_and_notes_nothing_about_boxes() -> None:
    curated = _described()
    curated["groups"][1]["external"] = True
    verified, report = verify_description.verify(curated, Path("."))
    assert "external" not in _group_of(verified, "vpc")
    assert "cites no network fact" not in report


def test_a_network_inside_a_network_becomes_a_plain_group_and_its_nodes_are_checked_against_the_outer_one() -> None:
    curated = _boxes(list(EXTERNAL))
    _group_of(curated, "shared")["parent"] = "vpc"
    verified, report = _verify(curated)
    assert _group_of(verified, "shared")["kind"] is None
    assert "group shared: network inside network group vpc, now a plain group" in report
    assert next(n for n in verified["nodes"] if n["id"] == "fn")["group"] == "acct"
