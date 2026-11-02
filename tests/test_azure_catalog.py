import json
from pathlib import Path

import pytest

from cartographer import clouds, icons
from cartographer.clouds import azure as azure_package
from cartographer.clouds.azure import AZURE
from cartographer.clouds.azure.rules import arm_icon
from cartographer.clouds.base import Catalog

no_attrs = lambda attr: None
DATA = Path(azure_package.__path__[0])


def test_cloud_identity_and_providers():
    assert (AZURE.name, AZURE.label, AZURE.providers, AZURE.managed_label) == (
        "azure", "Azure", ("azurerm", "azapi"), "Azure managed services")
    assert clouds.cloud_of_type("azurerm_lb") is AZURE and clouds.cloud_of_type("azapi_resource") is AZURE
    assert clouds.cloud_of_type("azuread_group") is None


def test_every_provider_type_has_a_row():
    assert [t for t in AZURE.provider_types if AZURE.catalog.row(t) is None] == []


def test_provider_types_are_the_sorted_pinned_list():
    assert len(AZURE.provider_types) == 1110
    assert AZURE.provider_types == sorted(set(AZURE.provider_types))
    assert {"azapi_resource", "azapi_update_resource", "azapi_data_plane_resource"} <= set(AZURE.provider_types)


def test_every_catalog_icon_exists():
    named = [f"azure:{r['icon']}" for r in AZURE.catalog.rows.values() if "icon" in r]
    named += [f"generic:{r['generic']}" for r in AZURE.catalog.rows.values() if "generic" in r]
    named += [f"azure:{i}" for i in AZURE.modules.values()]
    assert [i for i in named if not icons.known(i)] == []


def test_every_icon_file_exists_in_the_pinned_drawio_set():
    app = Path.home() / ".cache/cartographer/drawio/32.5.5/web"
    if not app.exists():
        pytest.skip("pinned draw.io app is not unpacked")
    assert [i["path"] for i in AZURE.icons.values() if not (app / "img/lib/azure2" / i["path"]).exists()] == []


def test_icon_table_shape():
    assert len(AZURE.icons) == 666
    assert all(set(i) == {"path", "title"} and i["path"].endswith(".svg") for i in AZURE.icons.values())
    assert icons.title("azure:azure_openai") == "OpenAI"


def test_icon_style_is_an_azure_image_with_the_label_below():
    style = AZURE.icon_style("key_vaults")
    assert style.startswith("image;aspect=fixed;html=1;points=[];align=center;fontSize=12;image=img/lib/azure2/security/")
    assert style.endswith("verticalLabelPosition=bottom;verticalAlign=top;")


def test_frame_styles_cover_every_frame_kind():
    assert set(AZURE.frame_styles) == {"cloud", "region", "account", "network", "subnet-public", "subnet-private", "subnet-isolated"}
    assert "#0078D4" in AZURE.frame_styles["cloud"] and "#0078D4" in AZURE.frame_styles["network"]
    assert "dashed=1" in AZURE.frame_styles["region"]


def test_every_generic_row_says_why():
    generic = {k: r for k, r in AZURE.catalog.rows.items() if "generic" in r}
    assert generic and all(r.get("why") for r in generic.values())


def test_resource_groups_are_not_drawn():
    r = AZURE.resolve("azurerm_resource_group", no_attrs)
    assert r.icon.startswith("generic:") and "resource groups are not drawn" in AZURE.catalog.rows["azurerm_resource_group"]["why"]


def test_virtual_machine_and_virtual_network_resolve_to_different_rows():
    vm, vnet = AZURE.resolve("azurerm_virtual_machine", no_attrs), AZURE.resolve("azurerm_virtual_network", no_attrs)
    assert (vm.icon, vnet.icon) == ("azure:virtual_machine", "azure:virtual_networks")
    assert vm.decided_by != vnet.decided_by


@pytest.mark.parametrize("tf_type", [
    "azurerm_role_assignment", "azurerm_monitor_diagnostic_setting", "azurerm_private_dns_zone_virtual_network_link",
    "azurerm_subnet_route_table_association", "azurerm_subnet_network_security_group_association",
    "azurerm_network_security_rule", "azurerm_network_interface", "azurerm_network_interface_security_group_association",
    "azurerm_nat_gateway_public_ip_association", "azurerm_key_vault_access_policy", "azurerm_linux_web_app_slot",
])
def test_the_specs_fold_list(tf_type):
    assert AZURE.resolve(tf_type, no_attrs).kind == "fold"


@pytest.mark.parametrize("tf_type", [
    "azurerm_frontdoor", "azurerm_cdn_frontdoor_profile", "azurerm_traffic_manager_profile", "azurerm_dns_zone",
])
def test_global_services(tf_type):
    assert AZURE.resolve(tf_type, no_attrs).scope == "global"


@pytest.mark.parametrize("tf_type", ["azurerm_private_dns_zone", "azurerm_virtual_network", "azurerm_storage_account"])
def test_regional_services(tf_type):
    assert AZURE.resolve(tf_type, no_attrs).scope == "regional"


def test_type_newer_than_the_list_keeps_the_family_icon_but_is_marked():
    r = AZURE.resolve("azurerm_kubernetes_cluster_brand_new", no_attrs)
    assert (r.kind, r.marked, r.reason) == ("icon", True, "type newer than provider list")
    r = AZURE.resolve("azurerm_zzz_unknown", no_attrs)
    assert (r.kind, r.marked, r.reason) == ("none", True, "type not in catalog")


def test_every_rule_row_names_a_rule_and_every_rule_is_used():
    used = {row["rule"] for row in AZURE.catalog.rows.values() if "rule" in row}
    assert used == set(AZURE.rules)


def test_data_files_stay_under_the_line_limit():
    for name in ("catalog.json", "provider_types.json", "icons.json", "arm_types.json", "modules.json"):
        assert len((DATA / name).read_text().splitlines()) < 1000


def test_catalog_json_is_valid_sorted_keys():
    assert list(rows := json.loads((DATA / "catalog.json").read_text())) == sorted(rows)


def test_arm_types_icons_exist_and_cover_the_catalog_icons():
    arm = json.loads((DATA / "arm_types.json").read_text())
    assert [i for i in arm.values() if i not in AZURE.icons] == []
    assert len(arm) >= 35
    for arm_type, icon in {"Microsoft.App/containerApps": "worker_container_app",
                           "Microsoft.Network/virtualNetworks": "virtual_networks"}.items():
        assert arm[arm_type] == icon


def test_arm_lookup_ignores_version_and_case():
    assert arm_icon("Microsoft.App/containerApps@2024-03-01") == "worker_container_app"
    assert arm_icon("microsoft.keyvault/VAULTS@2023-07-01") == "key_vaults"
    assert arm_icon("Microsoft.Nope/things@2024-01-01") is None


def avm_arm_key(source: str) -> str:
    provider, _, resource = source.split("/")[1].removeprefix("avm-res-").partition("-")
    return f"microsoft.{provider}/{resource}"


def arm_key_candidates(resource: str) -> set[str]:
    """AVM names use the singular, ARM type names the plural."""
    return {resource, resource + "s", resource + "es", resource.removesuffix("y") + "ies"}


def test_avm_resource_modules_resolve_through_arm_types():
    arm = {k.lower(): v for k, v in json.loads((DATA / "arm_types.json").read_text()).items()}
    avm = {s: i for s, i in AZURE.modules.items() if "/avm-res-" in s}
    assert len(avm) >= 30
    for source, icon in avm.items():
        provider, resource = avm_arm_key(source).split("/")
        assert icon in {arm.get(f"{provider}/{c}") for c in arm_key_candidates(resource)}, source


def test_avm_resource_module_resolves_and_a_pattern_module_is_unknown_and_marked():
    r = clouds.resolve_module("Azure/avm-res-network-virtualnetwork/azurerm")
    assert (r.kind, r.icon) == ("icon", "azure:virtual_networks")
    unknown = clouds.resolve_module("Azure/avm-ptn-aks-production/azurerm")
    assert (unknown.kind, unknown.marked, unknown.reason) == ("none", True, "unknown module")
    assert not [s for s in AZURE.modules if "avm-ptn-" in s]


def test_draft_catalog_lists_only_types_without_a_row(monkeypatch, tmp_path):
    from cartographer.clouds.azure import vendor

    types = tmp_path / "types.json"
    types.write_text(json.dumps(["azurerm_key_vault", "azurerm_zzz_thing"]))
    monkeypatch.setattr(vendor, "PROVIDER_TYPES", types)
    assert vendor.draft_catalog() == ['  "azurerm_zzz": {"icon": "?"},']


def test_vendor_parses_names_paths_and_titles(tmp_path):
    from cartographer.clouds.azure import vendor

    (tmp_path / "img/lib/azure2/other").mkdir(parents=True)
    (tmp_path / "img/lib/azure2/compute").mkdir()
    (tmp_path / "js/diagramly/sidebar").mkdir(parents=True)
    for rel in ("other/Cloud_Services_(extended_support).svg", "compute/Disks.svg", "other/Disks.svg"):
        (tmp_path / "img/lib/azure2" / rel).write_text("<svg/>")
    (tmp_path / vendor.SIDEBAR).write_text(
        "this.addAzure2ComputePalette(gn, r, sb, s + 'compute/');\n"
        "Sidebar.prototype.addAzure2ComputePalette = function(gn, r, sb, s)\n{\n"
        "this.createVertexTemplateEntry(s + 'Disks.svg;points=[[0,0,0]];', r * 0.1, r * 0.1, '', 'Disk Volumes', null, null, x)\n}\n")
    assert vendor.parse(tmp_path) == {
        "cloud_services_extended_support": {"path": "other/Cloud_Services_(extended_support).svg",
                                            "title": "Cloud Services (extended support)"},
        "disks": {"path": "compute/Disks.svg", "title": "Disk Volumes"},
    }


def test_catalog_class_is_shared_with_aws():
    assert isinstance(AZURE.catalog, Catalog)
