import json
from pathlib import Path

import pytest
from stub_cloud import StubCloud

from cartographer import clouds, icons
from cartographer.clouds import aws as aws_package
from cartographer.clouds.aws import AWS
from cartographer.clouds.base import UNRESOLVED, Catalog, Cloud, Resolution

no_attrs = lambda attr: None

FOLDED = [
    "aws_cloudwatch_log_group", "aws_iam_instance_profile", "aws_iam_policy", "aws_iam_role",
    "aws_iam_role_policy", "aws_iam_role_policy_attachment", "aws_kms_alias", "aws_lambda_alias",
    "aws_lambda_function_event_invoke_config", "aws_lambda_layer_version",
    "aws_s3_bucket_accelerate_configuration", "aws_s3_bucket_analytics_configuration",
    "aws_s3_bucket_cors_configuration", "aws_s3_bucket_intelligent_tiering_configuration",
    "aws_s3_bucket_lifecycle_configuration", "aws_s3_bucket_logging",
    "aws_s3_bucket_metadata_configuration", "aws_s3_bucket_object_lock_configuration",
    "aws_s3_bucket_ownership_controls", "aws_s3_bucket_policy", "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_replication_configuration", "aws_s3_bucket_request_payment_configuration",
    "aws_s3_bucket_server_side_encryption_configuration", "aws_s3_bucket_versioning",
    "aws_s3_bucket_website_configuration",
]


def catalog_icons(cloud: Cloud) -> list[str]:
    qualified = [f"{cloud.name}:{row['icon']}" for _, row in cloud.catalog.rows.items() if "icon" in row]
    qualified += [f"generic:{row['generic']}" for row in cloud.catalog.rows.values() if "generic" in row]
    return qualified + [f"{cloud.name}:{name}" for name in cloud.modules.values()]


def test_catalog_row_is_the_longest_key_on_a_token_boundary():
    catalog = Catalog({"aws_s3": {"icon": "s3"}, "aws_s3_bucket": {"icon": "b"}, "aws_s3_bucket_policy": {"fold": "owner"}})
    assert catalog.row("aws_s3_bucket_policy") == ("aws_s3_bucket_policy", {"fold": "owner"})
    assert catalog.row("aws_s3_bucket_policy_x")[0] == "aws_s3_bucket_policy"
    assert catalog.row("aws_s3_bucket")[0] == "aws_s3_bucket"
    assert catalog.row("aws_s3_bucketx")[0] == "aws_s3"
    assert catalog.row("aws_zzz") is None


def test_every_aws_provider_type_has_a_row():
    assert [t for t in AWS.provider_types if AWS.catalog.row(t) is None] == []


def test_provider_types_are_the_sorted_pinned_list():
    from cartographer.clouds.aws import ALIASES

    assert len(AWS.provider_types) == 1740 + len(ALIASES)
    assert AWS.provider_types == sorted(set(AWS.provider_types))


def test_every_catalog_icon_exists():
    assert [i for i in catalog_icons(AWS) if not icons.known(i)] == []


def test_every_generic_row_says_why():
    generic = {k: r for k, r in AWS.catalog.rows.items() if "generic" in r}
    assert generic and all(r.get("why") for r in generic.values())


def test_folds_are_exactly_the_types_folded_today():
    assert [t for t in AWS.provider_types if AWS.resolve(t, no_attrs).kind == "fold"] == FOLDED


def test_longest_prefix_wins():
    assert AWS.resolve("aws_s3_bucket_policy", no_attrs).kind == "fold"
    r = AWS.resolve("aws_s3_bucket", no_attrs)
    assert (r.kind, r.icon, r.decided_by) == ("icon", "aws:s3", "catalog aws_s3")
    assert AWS.resolve("aws_iam_policy_attachment", no_attrs).kind == "icon"


@pytest.mark.parametrize(("tf_type", "icon"), [
    ("aws_lambda_brand_new_thing", "aws:lambda"), ("aws_s3_bucket_new_configuration", "aws:s3"),
])
def test_type_newer_than_the_list_keeps_the_family_icon_but_is_marked(tf_type, icon):
    r = AWS.resolve(tf_type, no_attrs)
    assert (r.kind, r.icon, r.marked, r.reason) == ("icon", icon, True, "type newer than provider list")


def test_listed_types_and_exact_rows_are_not_marked():
    assert not AWS.resolve("aws_lambda_function", no_attrs).marked
    assert not AWS.resolve("aws_alb", no_attrs).marked


def test_type_newer_than_the_list_resolves_to_family_or_none():
    r = AWS.resolve("aws_zzz_unknown", no_attrs)
    assert (r.kind, r.marked, r.reason) == ("none", True, "type not in catalog")


@pytest.mark.parametrize(("tf_type", "icon"), [
    ("aws_opensearch_domain", "aws:elasticsearch_service"),
    ("aws_appconfig_application", "aws:app_config"),
    ("aws_prometheus_workspace", "aws:managed_service_for_prometheus"),
    ("aws_elb", "aws:elastic_load_balancing"),
])
def test_services_get_their_own_icon(tf_type, icon):
    assert AWS.resolve(tf_type, no_attrs).icon == icon


def test_generic_row_resolves_to_a_generic_icon():
    r = AWS.resolve("aws_account_alternate_contact", no_attrs)
    assert r.kind == "icon" and r.icon.startswith("generic:") and not r.marked


@pytest.mark.parametrize(("tf_type", "scope"), [
    ("aws_cloudfront_distribution", "global"), ("aws_route53_zone", "global"),
    ("aws_globalaccelerator_accelerator", "global"), ("aws_route53_resolver_endpoint", "regional"),
    ("aws_s3_bucket", "regional"),
])
def test_scope(tf_type, scope):
    assert AWS.resolve(tf_type, no_attrs).scope == scope


def test_drop_row():
    cloud = StubCloud("x", "X", ("x",), {}, {}, "m", catalog=Catalog({"x_noise": {"drop": True}}))
    assert cloud.resolve("x_noise_thing", no_attrs) == Resolution("drop", decided_by="catalog x_noise")


def test_rules_only_apply_to_their_own_type_not_the_family():
    assert AWS.resolve("aws_lb_listener", lambda a: UNRESOLVED) == AWS.resolve("aws_lb_listener", no_attrs)
    assert not AWS.resolve("aws_lb_listener", lambda a: UNRESOLVED).marked


def test_rule_with_unresolved_attribute_marks_and_keeps_base_icon():
    r = AWS.resolve("aws_db_instance", lambda a: UNRESOLVED)
    assert r.marked and r.icon == "aws:rds" and r.reason == "engine is not a literal"


def test_every_rule_row_names_a_rule_and_every_rule_is_used():
    used = {row["rule"] for row in AWS.catalog.rows.values() if "rule" in row}
    assert used == set(AWS.rules)


def test_module_sources():
    r = clouds.resolve_module("terraform-aws-modules/eks/aws")
    assert (r.kind, r.icon) == ("icon", "aws:eks")
    assert clouds.resolve_module("terraform-aws-modules/vpc/aws//modules/vpc-endpoints").icon == "aws:vpc"
    unknown = clouds.resolve_module("git::https://example.com/x.git")
    assert (unknown.kind, unknown.marked, unknown.reason, unknown.decided_by) == (
        "none", True, "unknown module", "curator, unknown module")


def test_required_modules_are_present():
    names = {"vpc", "eks", "rds", "rds-aurora", "lambda", "s3-bucket", "alb", "sqs", "sns", "dynamodb-table", "ecs",
             "cloudfront", "apigateway-v2"}
    assert all(f"terraform-aws-modules/{n}/aws" in AWS.modules for n in names)


def test_data_files_stay_under_the_line_limit():
    for name in ("catalog.json", "provider_types.json"):
        assert len(Path(aws_package.__path__[0], name).read_text().splitlines()) < 1000


def test_catalog_json_is_valid_sorted_keys():
    rows = json.loads(Path(aws_package.__path__[0], "catalog.json").read_text())
    assert list(rows) == sorted(rows)


def test_draft_catalog_lists_only_types_without_a_row(monkeypatch, tmp_path):
    from cartographer.clouds.aws import vendor

    types = tmp_path / "types.json"
    types.write_text(json.dumps(["aws_lambda_function", "aws_lambda_brand_new_thing", "aws_zzz_thing"]))
    monkeypatch.setattr(vendor, "PROVIDER_TYPES", types)
    assert vendor.draft_catalog() == ['  "aws_zzz": {"icon": "?"},']


def test_declared_types_resolve_through_the_owning_cloud() -> None:
    assert clouds.resolve_declared("aws_lb", {"load_balancer_type": "network"}).icon == "aws:elastic_load_balancing"
    unknown = clouds.resolve_declared("kubernetes_pod", {})
    assert (unknown.kind, unknown.marked) == ("none", True)


def test_description_verify_sets_icons_from_tf_type_and_marks_a_direct_cloud_icon(tmp_path) -> None:
    from cartographer import verify_description

    node = {"group": None, "multi": False, "tf": []}
    curated = {"format": 2, "source": "description", "title": "t", "groups": [], "edges": [], "omitted": [],
               "nodes": [{**node, "id": "a", "label": "a", "tf_type": "aws_sqs_queue"},
                         {**node, "id": "b", "label": "b", "icon": "aws:lambda"}],
               "externals": [{"id": "x", "label": "x", "tf_type": "aws_s3_bucket", "evidence": [{"stated": "s"}]}]}
    out, _ = verify_description.verify(curated, tmp_path)
    a, b = out["nodes"]
    assert (a["icon"], a["decided_by"], a["marked"]) == ("aws:sqs", "catalog aws_sqs", False)
    assert (b["decided_by"], b["marked"]) == ("curator", True)
    assert out["externals"][0]["icon"] == "aws:s3"


def test_a_declared_type_with_a_presence_rule_resolves() -> None:
    assert clouds.resolve_declared("azurerm_lb", {}).marked is True
    internal = clouds.resolve_declared("azurerm_lb", {"frontend_ip_configuration.subnet_id": "x"})
    assert internal.decided_by == "rule azurerm_lb frontend subnet_id set (internal)"


def test_a_cloud_must_define_its_icon_style() -> None:
    with pytest.raises(TypeError, match="icon_style"):
        Cloud("x", "X", ("x",), {}, {}, "m")
