from pathlib import Path

from cartographer import tf_extract

REPO = Path(__file__).parent / "fixtures" / "network"


def _facts() -> dict:
    return tf_extract.extract(Path("infra"), REPO)


def _vpcs() -> dict[str, dict]:
    return {v["address"]: v for v in _facts()["vpcs"]}


def _placements() -> dict[str, dict]:
    return {p["resource"]: p for p in _facts()["placements"]}


def test_local_vpc_cidrs_from_locals_associations_and_defaults() -> None:
    vpcs = _vpcs()
    assert vpcs["aws_vpc.main"]["cidrs"] == ["10.30.0.0/16", "10.31.0.0/20"]
    assert vpcs["aws_vpc.main"]["remote"] is False
    assert vpcs["aws_vpc.main"]["name"] == "main"
    assert vpcs["aws_vpc.main"]["file"] == "infra/main.tf"
    assert vpcs["aws_vpc.spare"]["cidrs"] == ["10.99.0.0/16"]


def test_unresolvable_cidr_gives_no_cidrs() -> None:
    assert _vpcs()["aws_vpc.dyn"]["cidrs"] == []


def test_remote_vpc_found_through_module_variable() -> None:
    remote = [v for v in _vpcs().values() if v["remote"]]
    assert len(remote) == 1
    assert remote[0]["address"] == "data.tfe_outputs.networking.nonsensitive_values.shared_vpc_id"
    assert remote[0]["name"] == "shared-vpc"
    assert remote[0]["cidrs"] == []


def test_local_subnet_tiers() -> None:
    placements = _placements()
    assert placements["aws_lb.front"]["tier"] == "public"
    assert "map_public_ip_on_launch" in placements["aws_lb.front"]["via"]
    assert placements["aws_instance.orders"]["tier"] == "private"
    assert placements["aws_db_instance.ledger"]["tier"] == "isolated"
    assert placements["aws_instance.misc"]["tier"] == "private"
    vpcs = {v["id"]: v["address"] for v in _facts()["vpcs"]}
    assert vpcs[placements["aws_lb.front"]["vpc"]] == "aws_vpc.main"


def test_remote_tier_from_output_name_through_module_variable() -> None:
    placement = _placements()["module.worker.aws_lambda_function.fn"]
    assert placement["tier"] == "private"
    vpcs = {v["id"]: v["name"] for v in _facts()["vpcs"]}
    assert vpcs[placement["vpc"]] == "shared-vpc"
    assert placement["file"] == "infra/modules/worker/main.tf"


def test_undecidable_or_unmatched_placements_are_skipped() -> None:
    placements = _placements()
    assert "aws_instance.lost" not in placements
    assert "aws_instance.outside" not in placements
    assert "aws_route_table_association.front" not in placements
    assert "module.worker.aws_security_group.sg" not in placements


def test_fact_ids_do_not_clash() -> None:
    facts = _facts()
    ids = [f["id"] for key in ("edges", "hints", "vpcs", "placements") for f in facts[key]]
    assert len(ids) == len(set(ids))
