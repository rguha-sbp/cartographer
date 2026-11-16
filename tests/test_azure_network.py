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
    assert tier_of("interpolated_tier_names", "azurerm_private_endpoint.pc") == ("public", "azurerm_subnet.c name")  # format()


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


def test_a_hub_lookup_that_shares_a_resource_group_with_a_local_vnet_stays_external(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "azurerm_virtual_network" "spoke" {\n  name = "spoke"\n  address_space = ["10.1.0.0/16"]\n'
        '  resource_group_name = "rg-net"\n}\n'
        'data "azurerm_virtual_network" "hub" {\n  name = "hub"\n'
        '  resource_group_name = azurerm_virtual_network.spoke.resource_group_name\n}\n'
        'data "azurerm_subnet" "hub_private" {\n  name = "private"\n'
        '  virtual_network_name = data.azurerm_virtual_network.hub.name\n'
        '  resource_group_name = azurerm_virtual_network.spoke.resource_group_name\n}\n'
        'resource "azurerm_virtual_network_peering" "p" {\n  virtual_network_name = azurerm_virtual_network.spoke.name\n'
        '  remote_virtual_network_id = data.azurerm_virtual_network.hub.id\n}\n'
        'resource "azurerm_private_endpoint" "pe" { subnet_id = data.azurerm_subnet.hub_private.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [
        ("azurerm_virtual_network.spoke", False), ("data.azurerm_virtual_network.hub", True)]
    hub = next(n["id"] for n in facts["networks"] if n["remote"])
    assert [(p["resource"], p["network"], p["tier"]) for p in facts["placements"]] == [("azurerm_private_endpoint.pe", hub, "private")]


def test_a_lookup_of_a_local_vnet_whose_resource_group_is_the_same_variable_is_that_vnet(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'variable "rg_name" {}\n'
        'resource "azurerm_virtual_network" "main" {\n  name = "main"\n  resource_group_name = var.rg_name\n'
        '  address_space = ["10.0.0.0/16"]\n}\n'
        'data "azurerm_virtual_network" "same" {\n  name = azurerm_virtual_network.main.name\n'
        '  resource_group_name = var.rg_name\n}\n'
        'resource "azurerm_subnet" "app_private" {\n  name = "app-private"\n  resource_group_name = var.rg_name\n'
        '  virtual_network_name = data.azurerm_virtual_network.same.name\n  address_prefixes = ["10.0.1.0/24"]\n}\n'
        'resource "azurerm_private_endpoint" "pe" { subnet_id = azurerm_subnet.app_private.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [("azurerm_virtual_network.main", False)]
    assert [(p["resource"], p["tier"]) for p in facts["placements"]] == [("azurerm_private_endpoint.pe", "private")]


def test_a_vm_is_placed_or_marked_through_a_nic_in_a_remote_or_looked_up_subnet(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "azurerm_virtual_network" "hub" {\n  name = "hub"\n  resource_group_name = "hub-rg"\n}\n'
        'data "azurerm_subnet" "hub_private" {\n  name = "private"\n'
        '  virtual_network_name = data.azurerm_virtual_network.hub.name\n  resource_group_name = "hub-rg"\n}\n'
        'data "tfe_outputs" "net" {\n  organization = "o"\n  workspace = "w"\n}\n'
        'resource "azurerm_network_interface" "nic" {\n  ip_configuration {\n'
        '    subnet_id = data.tfe_outputs.net.values.spoke_private_subnet_id\n  }\n}\n'
        'resource "azurerm_linux_virtual_machine" "vm" { network_interface_ids = [azurerm_network_interface.nic.id] }\n'
        'resource "azurerm_network_interface" "nic2" {\n  ip_configuration {\n'
        '    subnet_id = data.azurerm_subnet.hub_private.id\n  }\n}\n'
        'resource "azurerm_linux_virtual_machine" "vm2" { network_interface_ids = [azurerm_network_interface.nic2.id] }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    hub = next(n["id"] for n in facts["networks"] if n["address"] == "data.azurerm_virtual_network.hub")
    assert [(p["resource"], p["network"]) for p in facts["placements"]] == [("azurerm_linux_virtual_machine.vm2", hub)]
    reason = next(r.get("reason") for r in facts["resources"] if r["address"] == "azurerm_linux_virtual_machine.vm")
    assert "spoke_private_subnet_id fits no network this stack knows" in reason


@pytest.mark.parametrize(("vnet_rg", "lookup_rg"), [
    ("azurerm_resource_group.rg.name", "azurerm_virtual_network.main.resource_group_name"),
    ('"rg"', "azurerm_resource_group.rg.name"),
])
def test_a_lookup_whose_resource_group_reads_the_same_name_is_the_local_vnet(tmp_path: Path, vnet_rg: str, lookup_rg: str) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "azurerm_resource_group" "rg" {\n  name = "rg"\n}\n'
        f'resource "azurerm_virtual_network" "main" {{\n  name = "main"\n  resource_group_name = {vnet_rg}\n'
        '  address_space = ["10.0.0.0/16"]\n}\n'
        f'data "azurerm_virtual_network" "me" {{\n  name = azurerm_virtual_network.main.name\n  resource_group_name = {lookup_rg}\n}}\n'
        'resource "azurerm_virtual_network_peering" "p" {\n  virtual_network_name = "other"\n'
        '  remote_virtual_network_id = data.azurerm_virtual_network.me.id\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [("azurerm_virtual_network.main", False)]


def test_a_lookup_by_a_tag_of_a_local_vnet_is_external(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "azurerm_virtual_network" "main" {\n  name = "main"\n  resource_group_name = "rg"\n'
        '  address_space = ["10.0.0.0/16"]\n  tags = { peer = "dr" }\n}\n'
        'data "azurerm_virtual_network" "dr" {\n  name = azurerm_virtual_network.main.tags["peer"]\n  resource_group_name = "rg"\n}\n'
        'resource "azurerm_virtual_network_peering" "p" {\n  virtual_network_name = azurerm_virtual_network.main.name\n'
        '  remote_virtual_network_id = data.azurerm_virtual_network.dr.id\n}\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [(n["address"], n["remote"]) for n in facts["networks"]] == [
        ("azurerm_virtual_network.main", False), ("data.azurerm_virtual_network.dr", True)]


def test_a_subnet_whose_network_name_reads_two_networks_is_marked(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'variable "create" { default = false }\n'
        'data "tfe_outputs" "n" {\n  organization = "acme"\n  workspace = "network"\n}\n'
        'resource "azurerm_virtual_network" "own" {\n  count = var.create ? 1 : 0\n  name = "vnet-own"\n'
        '  address_space = ["10.0.0.0/16"]\n}\n'
        'resource "azurerm_subnet" "app" {\n'
        '  virtual_network_name = var.create ? azurerm_virtual_network.own[0].name : data.tfe_outputs.n.values.vnet_name\n'
        '  name = "snet-app"\n}\n'
        'resource "azurerm_private_endpoint" "pe" { subnet_id = azurerm_subnet.app.id }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert facts["placements"] == []
    assert next(r.get("reason") for r in facts["resources"] if r["address"] == "azurerm_private_endpoint.pe") == (
        "azurerm_subnet.app is in network azurerm_virtual_network.own or data.tfe_outputs.n.values.vnet_name,"
        " it does not single out one")


def test_a_subnet_lookup_picked_by_a_remote_subnet_output_is_in_the_network_it_names(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "hub" {\n  backend = "local"\n  config = { path = "hub.tfstate" }\n}\n'
        'data "azurerm_subnet" "app_private" {\n  name = data.terraform_remote_state.hub.outputs.app_subnet_name\n'
        '  virtual_network_name = data.terraform_remote_state.hub.outputs.vnet_name\n  resource_group_name = "rg-hub"\n}\n'
        'resource "azurerm_network_interface" "nic" {\n  ip_configuration {\n'
        '    subnet_id = data.azurerm_subnet.app_private.id\n  }\n}\n'
        'resource "azurerm_linux_virtual_machine" "vm" { network_interface_ids = [azurerm_network_interface.nic.id] }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    network = {n["id"]: n["name"] for n in facts["networks"]}
    assert {(p["resource"], network[p["network"]]) for p in facts["placements"]} >= {("azurerm_linux_virtual_machine.vm", "vnet")}
    assert all(r.get("reason") is None for r in facts["resources"] if r["address"] == "azurerm_linux_virtual_machine.vm")


@pytest.mark.parametrize(("rg", "tiers"), [("data.terraform_remote_state.net.outputs.rg_name", ["private"]), ('"rg-net"', [])])
def test_a_subnet_lookup_picked_by_the_name_of_a_subnet_output_object_takes_its_tier_only_in_the_state_resource_group(
        tmp_path: Path, rg: str, tiers: list[str]) -> None:
    (tmp_path / "main.tf").write_text(
        'data "terraform_remote_state" "net" {\n  backend = "local"\n  config = { path = "net.tfstate" }\n}\n'
        'data "azurerm_subnet" "s" {\n  name = data.terraform_remote_state.net.outputs.app_private_subnet.name\n'
        f'  virtual_network_name = data.terraform_remote_state.net.outputs.hub_vnet_name\n  resource_group_name = {rg}\n}}\n'
        'resource "azurerm_network_interface" "nic" {\n  ip_configuration {\n    subnet_id = data.azurerm_subnet.s.id\n  }\n}\n'
        'resource "azurerm_linux_virtual_machine" "vm" { network_interface_ids = [azurerm_network_interface.nic.id] }\n')
    facts = tf_extract.extract(Path("."), tmp_path)
    assert [p["tier"] for p in facts["placements"] if p["resource"].endswith(".vm")] == tiers


AZ_STATE = 'data "terraform_remote_state" "net" {\n  backend = "local"\n  config = { path = "net.tfstate" }\n}\n'


def _endpoint(name: str, subnet: str) -> str:
    return f'resource "azurerm_private_endpoint" "{name}" {{ subnet_id = {subnet}.id }}\n'


def _placed_in(tmp_path: Path, tf: str) -> tuple[set[tuple[str, str]], set[str]]:
    """(resource, network name) of each placement, and the networks' addresses."""
    (tmp_path / "main.tf").write_text(tf)
    facts = tf_extract.extract(Path("."), tmp_path)
    name = {n["id"]: n["name"] for n in facts["networks"]}
    return {(p["resource"], name[p["network"]]) for p in facts["placements"]}, {n["address"] for n in facts["networks"]}


def test_a_vnet_lookup_by_the_name_of_another_lookup_in_another_resource_group_is_another_network(tmp_path: Path) -> None:
    placed, networks = _placed_in(tmp_path,
        'data "azurerm_virtual_network" "weu" {\n  name = "vnet-hub"\n  resource_group_name = "rg-weu"\n}\n'
        'data "azurerm_virtual_network" "neu" {\n  name = data.azurerm_virtual_network.weu.name\n  resource_group_name = "rg-neu"\n}\n'
        'resource "azurerm_subnet" "a" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.weu.name\n}\n'
        'resource "azurerm_subnet" "b" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.neu.name\n}\n'
        + _endpoint("pe_a", "azurerm_subnet.a") + _endpoint("pe_b", "azurerm_subnet.b"))
    assert networks == {"data.azurerm_virtual_network.weu", "data.azurerm_virtual_network.neu"}
    assert placed == {("azurerm_private_endpoint.pe_a", "weu"), ("azurerm_private_endpoint.pe_b", "neu")}


@pytest.mark.parametrize("rg", ['"rg-network-dr"', "var.dr_rg", "data.azurerm_resource_group.dr.name"])
def test_a_vnet_lookup_by_a_remote_name_output_in_a_resource_group_the_state_does_not_give_is_another_network(
        tmp_path: Path, rg: str) -> None:
    placed, networks = _placed_in(tmp_path, AZ_STATE +
        'data "azurerm_virtual_network" "primary" {\n  name = data.terraform_remote_state.net.outputs.vnet_name\n'
        '  resource_group_name = data.terraform_remote_state.net.outputs.resource_group_name\n}\n'
        f'data "azurerm_virtual_network" "dr" {{\n  name = data.terraform_remote_state.net.outputs.vnet_name\n  resource_group_name = {rg}\n}}\n'
        'resource "azurerm_subnet" "p" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.primary.name\n}\n'
        'resource "azurerm_subnet" "d" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.dr.name\n}\n'
        + _endpoint("pe_a", "azurerm_subnet.p") + _endpoint("pe_b", "azurerm_subnet.d"))
    assert networks == {"data.terraform_remote_state.net.outputs.vnet_name", "data.azurerm_virtual_network.dr"}
    assert placed == {("azurerm_private_endpoint.pe_a", "vnet"), ("azurerm_private_endpoint.pe_b", "dr")}


def test_a_subnet_lookup_by_a_remote_name_output_in_a_literal_vnet_is_not_placed_in_the_remote_network(tmp_path: Path) -> None:
    placed, _ = _placed_in(tmp_path, AZ_STATE +
        'resource "azurerm_subnet" "own" {\n  name = "own-private"\n'
        '  virtual_network_name = data.terraform_remote_state.net.outputs.vnet_name\n}\n'
        'data "azurerm_subnet" "dr_app" {\n  name = data.terraform_remote_state.net.outputs.private_subnet_name\n'
        '  virtual_network_name = "vnet-dr"\n  resource_group_name = "rg-network-dr"\n}\n'
        + _endpoint("pe_dr", "data.azurerm_subnet.dr_app"))
    assert not any(resource == "azurerm_private_endpoint.pe_dr" for resource, _ in placed)


@pytest.mark.parametrize(("hub_rg", "passed_rg", "same"), [
    ('"rg-network"', "data.azurerm_virtual_network.hub.resource_group_name", True),
    ("var.network_rg", "var.network_rg", True),
    ("local.rg", "local.rg", True),
    ('"rg-network"', '"rg-network-dr"', False),
])
def test_a_module_lookup_of_a_vnet_the_caller_looked_up_is_that_network_when_its_resource_group_traces_to_the_same(
        tmp_path: Path, hub_rg: str, passed_rg: str, same: bool) -> None:
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "main.tf").write_text(
        'variable "vnet_name" {}\nvariable "vnet_rg" {}\n'
        'data "azurerm_virtual_network" "this" {\n  name = var.vnet_name\n  resource_group_name = var.vnet_rg\n}\n'
        'data "azurerm_subnet" "app_private" {\n  name = "app-private"\n'
        '  virtual_network_name = data.azurerm_virtual_network.this.name\n}\n'
        + _endpoint("app", "data.azurerm_subnet.app_private"))
    placed, networks = _placed_in(tmp_path,
        'variable "network_rg" {}\nlocals {\n  rg = var.network_rg\n}\n'
        f'data "azurerm_virtual_network" "hub" {{\n  name = "vnet-hub"\n  resource_group_name = {hub_rg}\n}}\n'
        f'module "app" {{\n  source = "./mod"\n  vnet_name = data.azurerm_virtual_network.hub.name\n  vnet_rg = {passed_rg}\n}}\n')
    assert networks == {"data.azurerm_virtual_network.hub" if same else "module.app.data.azurerm_virtual_network.this"}
    assert placed == {("module.app.azurerm_private_endpoint.app", "hub" if same else "this")}


@pytest.mark.parametrize("dr_rg", ['"${data.terraform_remote_state.net.outputs.rg_name}-dr"',
                                   'format("%s-dr", data.terraform_remote_state.net.outputs.rg_name)'])
def test_a_vnet_lookup_by_a_remote_name_in_a_resource_group_built_from_a_remote_output_is_another_network(
        tmp_path: Path, dr_rg: str) -> None:
    placed, networks = _placed_in(tmp_path, AZ_STATE +
        f'data "azurerm_virtual_network" "dr" {{\n  name = data.terraform_remote_state.net.outputs.vnet_name\n  resource_group_name = {dr_rg}\n}}\n'
        'resource "azurerm_subnet" "d" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.dr.name\n}\n'
        + _endpoint("pe_dr", "azurerm_subnet.d"))
    assert networks == {"data.azurerm_virtual_network.dr"}
    assert placed == {("azurerm_private_endpoint.pe_dr", "dr")}


def test_a_lookup_in_a_for_each_module_does_not_agree_with_another_for_each_module_by_the_text_each_value(
        tmp_path: Path) -> None:
    for mod, body in {
        "network": 'variable "rg" {}\nresource "azurerm_virtual_network" "this" {\n  name = "vnet-spoke"\n'
                   '  resource_group_name = var.rg\n  address_space = ["10.0.0.0/16"]\n}\n'
                   'output "vnet_name" { value = azurerm_virtual_network.this.name }\n'
                   'resource "azurerm_subnet" "s" {\n  name = "own-private"\n  virtual_network_name = azurerm_virtual_network.this.name\n}\n'
                   + _endpoint("own", "azurerm_subnet.s"),
        "app": 'variable "rg" {}\nvariable "vnet_name" {}\n'
               'data "azurerm_virtual_network" "spoke" {\n  name = var.vnet_name\n  resource_group_name = var.rg\n}\n'
               'data "azurerm_subnet" "private" {\n  name = "app-private"\n'
               '  virtual_network_name = data.azurerm_virtual_network.spoke.name\n}\n'
               + _endpoint("pe", "data.azurerm_subnet.private"),
    }.items():
        (tmp_path / mod).mkdir()
        (tmp_path / mod / "main.tf").write_text(body)
    placed, networks = _placed_in(tmp_path,
        'locals {\n  regions = { weu = { rg = "rg-net-weu" } }\n  apps = { billing = { rg = "rg-billing" } }\n}\n'
        'module "network" {\n  source = "./network"\n  for_each = local.regions\n  rg = each.value.rg\n}\n'
        'module "app" {\n  source = "./app"\n  for_each = local.apps\n  rg = each.value.rg\n'
        '  vnet_name = module.network["weu"].vnet_name\n}\n')
    assert "module.app.data.azurerm_virtual_network.spoke" in networks
    assert ("module.app.azurerm_private_endpoint.pe", "spoke") in placed


def test_a_dr_vnet_lookup_with_a_resource_group_built_from_the_state_in_a_local_is_another_network(tmp_path: Path) -> None:
    placed, networks = _placed_in(tmp_path, AZ_STATE +
        'locals {\n  dr_rg = "${data.terraform_remote_state.net.outputs.rg_name}-dr"\n}\n'
        'data "azurerm_virtual_network" "dr" {\n  name = data.terraform_remote_state.net.outputs.vnet_name\n  resource_group_name = local.dr_rg\n}\n'
        'resource "azurerm_subnet" "d" {\n  name = "app-private"\n  virtual_network_name = data.azurerm_virtual_network.dr.name\n}\n'
        + _endpoint("pe_dr", "azurerm_subnet.d"))
    assert networks == {"data.azurerm_virtual_network.dr"}
    assert placed == {("azurerm_private_endpoint.pe_dr", "dr")}


@pytest.mark.parametrize("vnet", ["each.value", "var.dr_vnet_name", '"vnet-spoke-b"'])
def test_a_subnet_lookup_by_a_remote_subnet_name_in_a_vnet_the_state_does_not_give_is_not_placed_in_the_state_network(
        tmp_path: Path, vnet: str) -> None:
    each = '  for_each = toset(["vnet-spoke-a", "vnet-spoke-b"])\n' if vnet == "each.value" else ""
    index = '["vnet-spoke-b"]' if each else ""
    placed, _ = _placed_in(tmp_path, AZ_STATE + 'variable "dr_vnet_name" {}\n'
        'resource "azurerm_subnet" "own" {\n  name = "own-private"\n'
        '  virtual_network_name = data.terraform_remote_state.net.outputs.vnet_name\n}\n'
        + _endpoint("own", "azurerm_subnet.own") +
        f'data "azurerm_subnet" "dr_app" {{\n{each}  name = data.terraform_remote_state.net.outputs.private_subnet_name\n'
        f'  resource_group_name = data.terraform_remote_state.net.outputs.rg_name\n  virtual_network_name = {vnet}\n}}\n'
        + _endpoint("pe", f"data.azurerm_subnet.dr_app{index}"))
    assert ("azurerm_private_endpoint.own", "vnet") in placed
    assert not any(resource == "azurerm_private_endpoint.pe" for resource, _ in placed)
