from functools import cache
from pathlib import Path

from cartographer import tf_extract

FIXTURES = Path(__file__).parent / "fixtures" / "azure"


@cache
def facts(case: str) -> dict:
    return tf_extract.extract(Path("."), FIXTURES / case)


def edges(case: str, kind: str) -> set[tuple[str, str, str]]:
    return {(e["src"], e["dst"], e["detail"]) for e in facts(case)["edges"] if e["kind"] == kind}


def resource(case: str, address: str) -> dict:
    return next(r for r in facts(case)["resources"] if r["address"] == address)


def test_role_assignment_from_a_system_identity_is_an_iam_edge_with_the_role_as_detail():
    assert edges("role_assignment_system_identity", "iam") == {
        ("azurerm_linux_web_app.app", "azurerm_storage_account.sa", "Storage Blob Data Reader")}


def test_role_assignment_from_a_user_assigned_identity_starts_at_the_resources_that_carry_it():
    assert edges("role_assignment_user_identity", "iam") == {
        ("azurerm_linux_function_app.fn", "azurerm_key_vault.kv", "Key Vault Secrets User")}


def test_role_assignments_are_folded_after_their_edge():
    assert resource("role_assignment_system_identity", "azurerm_role_assignment.read")["fold"] == "owner"


def test_a_resource_group_or_subscription_scope_is_a_cloud_wide_service_entry():
    services = {s["service"]: s for s in facts("role_assignment_wide_scope")["services"]}
    assert set(services) == {"azure:Reader", "azure:Monitoring Reader"}
    assert services["azure:Reader"] == {"service": "azure:Reader", "actions": ["Reader"],
                                       "principals": ["azurerm_linux_web_app.app"]}
    assert edges("role_assignment_wide_scope", "iam") == set()


def test_a_scope_that_cannot_be_resolved_is_counted_not_guessed():
    ex = tf_extract.Extractor(Path("."), FIXTURES / "role_assignment_wide_scope")
    found = ex.run()
    assert ex.stats["constructed_arns"] == 1
    assert "azure:Contributor" not in {s["service"] for s in found["services"]}


def test_key_vault_access_policy_is_an_iam_edge_with_its_permissions():
    assert edges("key_vault_access_policy", "iam") == {
        ("azurerm_linux_web_app.app", "azurerm_key_vault.kv", "key:Get,secret:Get,secret:List")}


def test_event_grid_subscription_is_a_trigger_from_its_source_to_the_function():
    assert ("azurerm_storage_account.sa", "azurerm_linux_function_app.fn", "azure_function_endpoint") in edges(
        "event_and_route_specs", "trigger")


def test_action_group_receiver_is_a_trigger_to_the_function():
    assert ("azurerm_monitor_action_group.ops", "azurerm_linux_function_app.fn", "azure_function_receiver") in edges(
        "event_and_route_specs", "trigger")


def test_stream_analytics_inputs_and_outputs_are_triggers_around_the_job():
    triggers = edges("event_and_route_specs", "trigger")
    assert ("azurerm_eventhub.events", "azurerm_stream_analytics_job.job", "stream_analytics_job_name") in triggers
    assert ("azurerm_stream_analytics_job.job", "azurerm_storage_account.sa", "storage_account_name") in triggers


def test_front_door_origin_is_a_route_to_the_origin_host_resource():
    assert ("azurerm_cdn_frontdoor_origin_group.g", "azurerm_linux_web_app.app", "host_name") in edges(
        "event_and_route_specs", "route")


def test_application_gateway_backend_pool_is_a_route_to_its_members():
    assert ("azurerm_application_gateway.gw", "azurerm_linux_web_app.app", "backend_address_pool") in edges(
        "event_and_route_specs", "route")


def test_location_is_literal_or_the_referenced_resource_groups_literal():
    case = "location_and_subscription"
    got = {n: resource(case, f"azurerm_storage_account.{n}")["location"]
           for n in ("via_group", "literal", "from_variable", "unknown")}
    assert got == {"via_group": "westeurope", "literal": "northeurope", "from_variable": "swedencentral", "unknown": None}


def test_subscription_is_the_literal_of_the_resources_provider_block_by_alias():
    case = "location_and_subscription"
    got = {n: resource(case, f"azurerm_storage_account.{n}")["subscription"]
           for n in ("via_group", "hub", "dynamic")}
    assert got == {"via_group": "11111111-1111-1111-1111-111111111111",
                   "hub": "22222222-2222-2222-2222-222222222222", "dynamic": None}


def test_a_resource_without_a_provider_block_has_a_null_subscription():
    assert resource("mixed", "azurerm_storage_account.data")["subscription"] is None


def test_mixed_stack_names_the_right_cloud_or_none_for_each_resource():
    by = {r["address"]: r for r in facts("mixed")["resources"]}
    assert by["aws_s3_bucket.logs"]["cloud"] == "aws"
    assert by["azurerm_storage_account.data"]["cloud"] == "azure"
    assert "cloud" not in by["kubernetes_namespace.apps"] and by["kubernetes_namespace.apps"]["marked"] is False
    assert "icon" not in by["kubernetes_namespace.apps"]
    assert (by["module.vault"]["cloud"], by["module.vault"]["icon"]) == ("azure", "azure:key_vaults")
    assert "cloud" not in by["module.landing_zone"] and by["module.landing_zone"]["marked"] is True
    assert by["module.landing_zone"]["reason"] == "unknown module"


def test_mixed_stack_never_lets_random_resources_reach_the_facts():
    found = facts("mixed")
    assert not [r for r in found["resources"] if r["type"].startswith("random_")]
    assert not [e for e in found["edges"] if "random_" in e["src"] + e["dst"]]
    assert {n["cloud"] for n in found["networks"]} <= {"aws", "azure"}


def test_load_balancer_is_public_or_internal_by_its_frontend_blocks():
    got = {n: resource("lb_exposure", f"azurerm_lb.{n}") for n in (
        "public_ip", "public_prefix", "internal", "internal_private_ip", "second_frontend_public", "no_frontend")}
    assert {n: (r["icon"], r["marked"], r.get("decided_by")) for n, r in got.items()} == {
        "public_ip": ("azure:load_balancers", False, "rule azurerm_lb frontend public_ip_address_id set (public)"),
        "public_prefix": ("azure:load_balancers", False, "rule azurerm_lb frontend public_ip_prefix_id set (public)"),
        "internal": ("azure:load_balancers", False, "rule azurerm_lb frontend subnet_id set (internal)"),
        "internal_private_ip": ("azure:load_balancers", False, "rule azurerm_lb frontend private_ip_address set (internal)"),
        "second_frontend_public": ("azure:load_balancers", False, "rule azurerm_lb frontend public_ip_address_id set (public)"),
        "no_frontend": ("azure:load_balancers", True, "rule azurerm_lb frontend_ip_configuration absent"),
    }
    assert got["no_frontend"]["reason"] == "frontend_ip_configuration absent"


def test_a_module_providers_map_carries_the_aliased_providers_subscription_into_the_module():
    case = "module_provider_alias"
    got = {m: (resource(case, f"module.{m}.azurerm_storage_account.sa")["location"],
               resource(case, f"module.{m}.azurerm_storage_account.sa")["subscription"]) for m in ("plain", "hub")}
    assert got == {"plain": ("westeurope", "11111111-1111-1111-1111-111111111111"),
                   "hub": ("northeurope", "22222222-2222-2222-2222-222222222222")}


def test_inline_key_vault_access_policies_are_iam_edges_like_the_standalone_resource():
    assert edges("key_vault_inline_policy", "iam") == {
        ("azurerm_linux_web_app.app", "azurerm_key_vault.kv", "key:Get,secret:Get,secret:List"),
        ("azurerm_linux_web_app.worker", "azurerm_key_vault.kv", "secret:Get")}
