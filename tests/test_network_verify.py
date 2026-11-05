import copy
from pathlib import Path

import pytest

from cartographer import tf_extract, tf_verify, verify_description
from cartographer.curated_format import FRAME_KINDS
from cartographer.verify_shared import cloud_warnings, group_claims

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


def test_edges_cannot_cite_network_facts() -> None:
    curated = _curated()
    curated["nodes"].append(_node("vm", "aws_instance.orders", None))
    curated["edges"] = [{"src": "lb", "dst": "vm", "label": "x", "flow": "web", "evidence": [{"fact": VPC["id"]}]}]
    verified, report = _verify(curated)
    assert verified["edges"] == []
    assert "is not an edge fact" in report


SHARED_FN = "module.worker.aws_lambda_function.fn"
NOWHERE = "aws_instance.lost"


def _shared_vpc(*account_groups: dict, vpc_parent: str = "netacct", **vpc: object) -> dict:
    """The worker Lambda in the shared VPC, whose frame sits in `vpc_parent`, and a node outside any network in `acct`."""
    return _curated(
        groups=[
            _group("acct", "account", None),
            *account_groups,
            _group("apps", None, "acct"),
            _group("shared", "network", vpc_parent, evidence=[{"fact": REMOTE["id"]}], **vpc),
            _group("priv", "subnet", "shared", tier="private", evidence=[{"fact": PLACED[SHARED_FN]}]),
            _group("work", None, "priv"),
        ],
        nodes=[_node("fn", SHARED_FN, "work"), _node("vm", NOWHERE, "apps")],
    )


NETWORKING = _group("netacct", "account", None, label="Networking account")


def test_a_shared_vpc_in_an_account_frame_of_its_own_is_a_warning() -> None:
    curated = _shared_vpc(NETWORKING)
    verified, report = _verify(curated)
    assert verified["groups"] == curated["groups"]
    assert "group shared: shared network sits in account netacct, which holds none of the stack's other nodes" in report
    assert "draw it in the stack's account (acct) with `owner` set" in report
    assert group_claims(curated) <= group_claims(verified)  # a warning, it does not stop the build


def test_the_warning_names_every_account_of_the_stack() -> None:
    curated = _shared_vpc(NETWORKING, _group("acct2", "account", None), _group("more", None, "acct2"))
    curated["nodes"].append(_node("misc", "aws_instance.misc", "more"))
    verified, report = _verify(curated)
    assert verified["groups"] == curated["groups"]
    assert "draw it in the stack's account (acct, acct2)" in report


def test_no_warning_when_no_other_account_frame_holds_a_node() -> None:
    curated = _shared_vpc(NETWORKING)
    curated["nodes"] = curated["nodes"][:1]
    _, report = _verify(curated)
    assert "shared network sits in account" not in report


def test_no_warning_when_the_other_account_is_of_another_cloud() -> None:
    curated = _shared_vpc(NETWORKING)
    curated["groups"][0]["cloud"] = "azure"
    _, report = _verify(curated)
    assert "shared network sits in account" not in report


def test_a_node_without_placement_in_the_shared_vpc_keeps_it_shared() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="Networking account")
    curated["nodes"].append(_node("sg", "module.worker.aws_security_group.sg", "shared"))
    verified, _ = _verify(curated)
    assert _group_of(verified, "shared")["owner"] == "Networking account"


def test_a_shared_vpc_with_no_placed_node_is_known_by_its_remote_fact() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="Networking account")
    curated["nodes"] = [_node("sg", "module.worker.aws_security_group.sg", "shared"), curated["nodes"][1]]
    verified, _ = _verify(curated)
    assert _group_of(verified, "shared")["owner"] == "Networking account"


OWNER_DROPPED = "owner dropped, it cites no remote network fact whose source names it"


def test_the_remote_source_must_name_the_owner() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="Security account")
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "shared")
    assert f"group shared: {OWNER_DROPPED}" in report


def test_owner_needs_the_remote_network_fact_in_evidence() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="Networking account")
    _group_of(curated, "shared")["evidence"] = []
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "shared")
    assert f"group shared: {OWNER_DROPPED}" in report


def test_an_owner_that_looks_like_a_secret_is_dropped() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="password = hunter2hunter2")
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "shared")
    assert "group shared: owner looks like a secret, dropped" in report


def test_a_code_citation_does_not_back_a_networks_cidrs() -> None:
    curated = _shared_vpc(vpc_parent="acct", cidrs=["10.9.0.0/16"])
    _group_of(curated, "shared")["evidence"].append({"file": "infra/main.tf", "line": 83, "contains": "networking"})
    verified, report = _verify(curated)
    assert "cidrs" not in _group_of(verified, "shared")
    assert "a network's cidrs come from its network fact" in report


@pytest.mark.parametrize(("owner", "kept"), [
    ("Networking account", True), ("networking", True), ("Network account", False), ("Net", False),
    ("Outputs account", False), ("Tfe account", False)])
def test_the_owner_must_be_named_as_whole_words(owner: str, kept: bool) -> None:
    curated = _shared_vpc(vpc_parent="acct", owner=owner)
    verified, _ = _verify(curated)
    assert ("owner" in _group_of(verified, "shared")) is kept


def test_a_shared_vpc_already_in_the_stacks_account_stays() -> None:
    curated = _shared_vpc(vpc_parent="acct", owner="Networking account")
    verified, report = _verify(curated)
    assert verified["groups"] == curated["groups"]
    assert "Warnings (0)" in report


def test_a_single_account_frame_is_left_alone() -> None:
    curated = _shared_vpc(vpc_parent="acct")
    curated["nodes"] = curated["nodes"][:1]
    curated["groups"] = [g for g in curated["groups"] if g["id"] != "apps"]
    verified, _ = _verify(curated)
    assert verified["groups"] == curated["groups"]


def test_owner_on_a_vpc_the_stack_creates_is_dropped() -> None:
    curated = _curated()
    curated["groups"][1]["owner"] = "Networking account"
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "vpc")
    assert f"group vpc: {OWNER_DROPPED}" in report
    assert tf_verify.needs_attention(curated, verified)


def test_owner_on_a_vpc_the_stack_creates_holding_a_remote_placed_node_is_dropped() -> None:
    curated = _curated()
    curated["groups"][1]["owner"] = "Networking account"
    curated["nodes"].append(_node("fn", SHARED_FN, "vpc"))
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "vpc")
    assert f"group vpc: {OWNER_DROPPED}" in report


def test_owner_on_a_group_that_is_not_a_network_is_dropped() -> None:
    curated = _curated()
    curated["groups"][2]["owner"] = "Networking account"
    verified, report = _verify(curated)
    assert "owner" not in _group_of(verified, "pub")
    assert "group pub: owner on a group that is not a network, dropped" in report


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


def test_described_owner_on_a_network_passes() -> None:
    curated = _described()
    curated["groups"][1]["owner"] = "Networking account"
    verified, _ = verify_description.verify(curated, Path("."))
    assert verified["groups"] == curated["groups"]


def test_described_owner_without_evidence_is_dropped() -> None:
    curated = _described()
    curated["groups"][1] = {**curated["groups"][1], "owner": "Networking account", "evidence": []}
    curated["groups"][1].pop("cidrs", None)
    verified, report = verify_description.verify(curated, Path("."))
    assert "owner" not in _group_of(verified, curated["groups"][1]["id"])
    assert "owner dropped, no evidence" in report
