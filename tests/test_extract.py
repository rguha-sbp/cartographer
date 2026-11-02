from pathlib import Path

import pytest

from cartographer import tf_extract

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def mini_facts() -> dict:
    return tf_extract.extract(Path("mini"), FIXTURES)


@pytest.fixture(scope="module")
def neutral_facts() -> dict:
    return tf_extract.extract(Path("neutral"), FIXTURES)


def by_address(facts: dict, address: str) -> dict:
    return next(r for r in facts["resources"] if r["address"] == address)


def test_extract_finds_resources_and_iam_edge(mini_facts: dict) -> None:
    addresses = {r["address"] for r in mini_facts["resources"]}
    assert {"aws_lambda_function.fn", "aws_s3_bucket.data"} <= addresses
    edges = [(e["src"], e["dst"], e["kind"]) for e in mini_facts["edges"]]
    assert ("aws_lambda_function.fn", "aws_s3_bucket.data", "iam") in edges


def test_resources_carry_cloud_and_icon(mini_facts: dict) -> None:
    fn = by_address(mini_facts, "aws_lambda_function.fn")
    assert (fn["cloud"], fn["icon"], fn["marked"]) == ("aws", "aws:lambda", False)
    assert fn["decided_by"] == "catalog aws_lambda"


def test_a_folded_resource_has_no_icon(mini_facts: dict) -> None:
    role = by_address(mini_facts, "aws_iam_role.fn")
    assert role["fold"] == "owner" and "icon" not in role


def test_random_resources_never_reach_the_facts(neutral_facts: dict) -> None:
    assert not any(r["type"].startswith("random_") for r in neutral_facts["resources"])
    assert not any("random_id" in f"{e['src']}{e['dst']}" for e in neutral_facts["edges"])


def test_other_providers_have_no_cloud_and_are_unmarked(neutral_facts: dict) -> None:
    ns = by_address(neutral_facts, "kubernetes_namespace.apps")
    assert "cloud" not in ns and "icon" not in ns and ns["marked"] is False


def test_uses_edges_skip_folded_types(neutral_facts: dict) -> None:
    assert neutral_facts["edges"] == []
    assert by_address(neutral_facts, "aws_cloudwatch_log_group.fn")["fold"] == "owner"


def test_a_non_literal_rule_attribute_marks_the_resource(neutral_facts: dict) -> None:
    lb = by_address(neutral_facts, "aws_lb.front")
    assert lb["icon"] == "aws:elastic_load_balancing" and lb["marked"] is True
    assert lb["reason"] == "load_balancer_type is not a literal"
