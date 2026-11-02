from functools import cache
from pathlib import Path

import pytest

from cartographer import tf_extract

FIXTURES = Path(__file__).parent / "fixtures" / "azure"


@cache
def facts(case: str) -> dict:
    return tf_extract.extract(Path("."), FIXTURES / case)


def placements(case: str) -> dict[str, dict]:
    return {p["resource"]: p for p in facts(case)["placements"]}


def tier_of(case: str, resource: str) -> tuple[str, str]:
    placed = placements(case)[resource]
    return placed["tier"], placed["via"]


@pytest.mark.parametrize(("case", "resource", "tier", "via"), [
    ("public_nic_ip", "azurerm_linux_virtual_machine.web", "public", "azurerm_subnet.app public ip"),
    ("gateway_names_backend_nic", "azurerm_application_gateway.gw", "public", "azurerm_subnet.agw public ip"),
    ("gateway_names_backend_nic", "azurerm_linux_virtual_machine.vm", "private", "azurerm_subnet.app default"),
    ("public_reserved_names", "azurerm_virtual_network_gateway.gw", "public", "azurerm_subnet.gw reserved name GatewaySubnet"),
    ("public_reserved_names", "azurerm_bastion_host.bastion", "public", "azurerm_subnet.bastion reserved name AzureBastionSubnet"),
    ("public_reserved_names", "azurerm_firewall.fw", "public", "azurerm_subnet.fw reserved name AzureFirewallSubnet"),
    ("private_nat_gateway", "azurerm_linux_virtual_machine_scale_set.workers", "private", "azurerm_subnet.work nat gateway"),
    ("private_lb_outbound_rule", "azurerm_linux_virtual_machine.vm", "private", "azurerm_subnet.work load balancer outbound rule"),
    ("private_user_defined_route", "azurerm_linux_virtual_machine_scale_set.inline", "private", "azurerm_subnet.inline_route route to virtual appliance"),
    ("private_user_defined_route", "azurerm_linux_virtual_machine_scale_set.separate", "private", "azurerm_subnet.separate_route route to virtual appliance"),
    ("isolated_by_flag", "azurerm_linux_virtual_machine_scale_set.locked", "isolated", "azurerm_subnet.locked default_outbound_access_enabled = false"),
    ("isolated_by_flag", "azurerm_linux_virtual_machine_scale_set.nat", "private", "azurerm_subnet.locked_with_nat nat gateway"),
    ("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.named_public", "public", "azurerm_subnet.named_public name"),
    ("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.named_isolated", "isolated", "azurerm_subnet.named_isolated name"),
    ("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.unnamed", "private", "azurerm_subnet.unnamed default"),
    ("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.tagged", "isolated", "azurerm_subnet.tagged name"),
])
def test_subnet_tier_and_what_decided_it(case, resource, tier, via):
    assert tier_of(case, resource) == (tier, via)


def test_a_default_route_that_is_not_to_an_appliance_is_not_an_outbound_path():
    assert tier_of("private_user_defined_route", "azurerm_linux_virtual_machine_scale_set.direct")[1] == "azurerm_subnet.direct_route default"


def test_default_outbound_access_absent_or_true_is_never_isolated():
    assert tier_of("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.unnamed")[0] == "private"
    assert tier_of("fallback_name_and_default", "azurerm_linux_virtual_machine_scale_set.flag_on")[0] == "private"


def test_inline_and_separate_subnets_both_count():
    assert tier_of("inline_and_separate_subnets", "azurerm_linux_virtual_machine_scale_set.inl") == (
        "isolated", "azurerm_virtual_network.inl.subnet[0] name")
    assert tier_of("inline_and_separate_subnets", "azurerm_linux_virtual_machine_scale_set.sep") == (
        "public", "azurerm_subnet.b name")


def test_vm_is_placed_through_its_nic_and_the_nic_is_not():
    assert tier_of("vm_via_nic", "azurerm_linux_virtual_machine.app") == ("private", "azurerm_subnet.app default")
    assert "azurerm_network_interface.nic" not in placements("vm_via_nic")


def test_scale_set_is_placed_by_its_nested_subnet_id():
    assert tier_of("scale_set", "azurerm_linux_virtual_machine_scale_set.workers")[0] == "private"


def test_private_endpoint_is_placed_and_its_service_is_not():
    found = placements("private_endpoint")
    assert "azurerm_private_endpoint.sql" in found and "azurerm_mssql_server.sql" not in found
    assert set(found) == {"azurerm_private_endpoint.sql"}


def test_vnet_integration_is_a_network_edge_and_never_a_placement():
    assert "azurerm_linux_web_app.app" not in placements("vnet_integration")
    edges = [e for e in facts("vnet_integration")["edges"] if e["kind"] == "network"]
    assert [(e["src"], e["dst"], e["detail"]) for e in edges if e["src"] == "azurerm_linux_web_app.app"] == [
        ("azurerm_linux_web_app.app", "azurerm_subnet.integration", "virtual_network_subnet_id")]


def test_subnet_injected_flexible_server_is_placed():
    assert tier_of("flexible_server", "azurerm_postgresql_flexible_server.pg")[0] == "private"


def test_peered_vnets_are_two_networks_with_their_address_spaces():
    networks = {n["address"]: n for n in facts("peered_networks")["networks"]}
    assert networks["azurerm_virtual_network.hub"]["cidrs"] == ["10.0.0.0/16", "10.10.0.0/16"]
    assert networks["azurerm_virtual_network.spoke"]["cidrs"] == ["10.1.0.0/16"]
    assert networks["azurerm_virtual_network.dynamic"]["cidrs"] == []
    assert not any(n["remote"] for n in networks.values()) and len(networks) == 3


def test_remote_networks_from_data_sources_and_outputs_have_names_and_no_cidrs():
    remote = {n["address"]: n for n in facts("remote_networks")["networks"] if n["remote"]}
    assert remote["data.azurerm_virtual_network.hub"]["name"] == "hub"
    shared = remote["data.tfe_outputs.net.nonsensitive_values.shared_vnet_id"]
    assert (shared["name"], shared["cidrs"]) == ("shared-vnet", [])
    ids = {n["id"]: n["name"] for n in facts("remote_networks")["networks"]}
    placed = placements("remote_networks")["azurerm_linux_virtual_machine_scale_set.w"]
    assert (ids[placed["network"]], placed["tier"]) == ("shared-vnet", "private")


def test_interpolated_subnet_names_still_inform_the_tier():
    assert tier_of("interpolated_tier_names", "azurerm_private_endpoint.pa") == ("public", "azurerm_subnet.a name")
    assert tier_of("interpolated_tier_names", "azurerm_private_endpoint.pb") == ("isolated", "azurerm_subnet.b name")


def test_a_remote_network_named_by_a_name_output_drops_the_name_suffix_and_is_placed():
    nets = {n["id"]: n["name"] for n in facts("remote_network_by_name")["networks"]}
    placed = placements("remote_network_by_name")["azurerm_private_endpoint.pa"]
    assert (nets[placed["network"]], placed["tier"]) == ("hub-vnet", "private")


def test_every_network_and_placement_names_azure_and_ids_do_not_clash():
    for case in ("public_nic_ip", "peered_networks", "remote_networks"):
        found = facts(case)
        assert {n["cloud"] for n in found["networks"]} == {"azure"}
        assert {p["cloud"] for p in found["placements"]} <= {"azure"}
        ids = [f["id"] for key in ("edges", "hints", "networks", "placements") for f in found[key]]
        assert len(ids) == len(set(ids))


def test_a_public_ip_on_an_application_gateway_frontend_or_nic_makes_its_subnet_public():
    assert tier_of("lb_exposure", "azurerm_application_gateway.gw") == ("public", "azurerm_subnet.gw public ip")
    assert tier_of("lb_exposure", "azurerm_linux_virtual_machine.vm") == ("public", "azurerm_subnet.edge public ip")


@pytest.mark.parametrize(("resource", "tier", "via"), [
    ("by_name", "isolated", "azurerm_virtual_network.v.subnet[1] name"),
    ("by_prefix", "public", "azurerm_virtual_network.v.subnet[0] name"),
])
def test_a_reference_that_carries_a_subnet_name_or_prefix_picks_that_inline_subnet(resource, tier, via):
    assert tier_of("several_inline_subnets", f"azurerm_linux_virtual_machine_scale_set.{resource}") == (tier, via)


@pytest.mark.parametrize("resource", ["ambiguous", "unknown_name"])
def test_an_unindexed_reference_to_several_inline_subnets_is_marked_not_placed(resource):
    address = f"azurerm_linux_virtual_machine_scale_set.{resource}"
    assert address not in placements("several_inline_subnets")
    entry = next(r for r in facts("several_inline_subnets")["resources"] if r["address"] == address)
    assert (entry["marked"], entry["reason"]) == (True, "azurerm_virtual_network.v has 3 inline subnets and the reference does not single out one")


def test_an_internal_frontend_does_not_make_its_subnet_public_because_another_frontend_is():
    assert tier_of("lb_mixed_frontends", "azurerm_lb.mixed") == ("private", "azurerm_subnet.inner default")


@pytest.mark.parametrize(("case", "resource", "tier"), [
    ("dual_frontend_gateway", "azurerm_application_gateway.g", "public"),
    ("nic_two_ip_configs", "azurerm_linux_virtual_machine.web", "public"),
    ("lb_private_only", "azurerm_lb.internal", "private"),
])
def test_a_resource_with_a_public_frontend_is_public_in_every_subnet_a_private_frontend_shares(case, resource, tier):
    assert tier_of(case, resource)[0] == tier


def test_each_resource_body_is_scanned_for_references_once(monkeypatch):
    from cartographer.clouds.azure import network

    seen: list[dict] = []
    original = network.Network.refs

    def counting(self, inst, obj):
        if isinstance(obj, dict):
            seen.append(obj)
        return original(self, inst, obj)

    monkeypatch.setattr(network.Network, "refs", counting)
    tf_extract.extract(Path("."), FIXTURES / "vm_via_nic")
    assert len(seen) == len({id(o) for o in seen})


def test_blocks_given_as_expressions_are_skipped_not_crashed_on():
    assert placements("subnet_expression") == {}
