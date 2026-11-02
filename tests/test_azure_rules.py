import pytest

from cartographer import icons
from cartographer.clouds.azure import AZURE
from cartographer.clouds.base import UNRESOLVED


def attrs(**values):
    def get(attr, present=False, every=False):
        found = values.get(attr.replace(".", "_"))
        return ([] if found is None else [found]) if every else found

    return get


def unresolved(*names):
    def get(attr, present=False, every=False):
        found = UNRESOLVED if attr.replace(".", "_") in names else None
        return ([] if found is None else [found]) if every else found

    return get


def frontends(*set_attrs):
    return lambda attr, present=False: attr.removeprefix("frontend_ip_configuration.") in set_attrs if present else None


@pytest.mark.parametrize(("set_attrs", "decided"), [
    (("public_ip_address_id",), "frontend public_ip_address_id set (public)"),
    (("public_ip_prefix_id",), "frontend public_ip_prefix_id set (public)"),
    (("subnet_id",), "frontend subnet_id set (internal)"),
    (("private_ip_address",), "frontend private_ip_address set (internal)"),
    (("subnet_id", "public_ip_address_id"), "frontend public_ip_address_id set (public)"),
])
def test_lb_rule(set_attrs, decided):
    r = AZURE.resolve("azurerm_lb", frontends(*set_attrs))
    assert (r.icon, r.marked, r.decided_by) == ("azure:load_balancers", False, f"rule azurerm_lb {decided}")


def test_lb_without_a_frontend_block_is_marked_with_the_base_icon():
    r = AZURE.resolve("azurerm_lb", frontends())
    assert (r.icon, r.marked, r.reason) == ("azure:load_balancers", True, "frontend_ip_configuration absent")


@pytest.mark.parametrize(("tier", "decided"), [
    ("Standard_v2", 'sku.tier = "Standard_v2"'), ("WAF_v2", 'sku.tier = "WAF_v2" (web application firewall)'),
    ("WAF", 'sku.tier = "WAF" (web application firewall)'), (None, "sku.tier absent"),
])
def test_application_gateway_rule(tier, decided):
    r = AZURE.resolve("azurerm_application_gateway", attrs(sku_tier=tier))
    assert (r.icon, r.marked, r.decided_by) == ("azure:application_gateways", False, f"rule azurerm_application_gateway {decided}")


def test_application_gateway_unresolved_marks():
    r = AZURE.resolve("azurerm_application_gateway", unresolved("sku_tier"))
    assert (r.icon, r.marked, r.reason) == ("azure:application_gateways", True, "sku.tier is not a literal")


@pytest.mark.parametrize(("kind", "icon"), [
    ("OpenAI", "azure_openai"), ("AIServices", "ai_foundry"), ("SpeechServices", "speech_services"),
    ("FormRecognizer", "form_recognizers"), ("ComputerVision", "computer_vision"), ("Face", "face_apis"),
    ("TextAnalytics", "language_services"), ("ContentSafety", "content_safety"), ("TextTranslation", "translator_text"),
    ("CognitiveServices", "cognitive_services"), ("SomethingNew", "cognitive_services"), (None, "cognitive_services"),
])
def test_cognitive_account_rule(kind, icon):
    r = AZURE.resolve("azurerm_cognitive_account", attrs(kind=kind))
    assert (r.icon, r.marked) == (f"azure:{icon}", False)


def test_cognitive_account_rule_decided_by_names_the_kind():
    assert AZURE.resolve("azurerm_cognitive_account", attrs(kind="OpenAI")).decided_by == 'rule azurerm_cognitive_account kind = "OpenAI"'


def test_cognitive_account_unresolved_kind_marks_and_keeps_base_icon():
    r = AZURE.resolve("azurerm_cognitive_account", unresolved("kind"))
    assert (r.icon, r.marked, r.reason) == ("azure:cognitive_services", True, "kind is not a literal")


@pytest.mark.parametrize(("attributes", "icon"), [
    ({"is_hns_enabled": "true"}, "data_lake_storage_gen1"),
    ({"is_hns_enabled": "false"}, "storage_accounts"),
    ({"account_kind": "BlobStorage"}, "blob_block"),
    ({"account_kind": "FileStorage"}, "storage_azure_files"),
    ({"account_kind": "StorageV2"}, "storage_accounts"),
    ({"account_kind": "StorageV2", "is_hns_enabled": "true"}, "data_lake_storage_gen1"),
    ({}, "storage_accounts"),
])
def test_storage_account_rule(attributes, icon):
    r = AZURE.resolve("azurerm_storage_account", attrs(**attributes))
    assert (r.icon, r.marked) == (f"azure:{icon}", False)


@pytest.mark.parametrize("missing", ["is_hns_enabled", "account_kind"])
def test_storage_account_unresolved_marks_and_keeps_base_icon(missing):
    r = AZURE.resolve("azurerm_storage_account", unresolved(missing))
    assert (r.icon, r.marked, r.reason) == ("azure:storage_accounts", True, f"{missing} is not a literal")


@pytest.mark.parametrize(("attributes", "api"), [
    ({}, "NoSQL"), ({"kind": "GlobalDocumentDB"}, "NoSQL"), ({"kind": "MongoDB"}, "MongoDB"),
    ({"capabilities_name": "EnableCassandra"}, "Cassandra"), ({"capabilities_name": "EnableTable"}, "Table"),
    ({"capabilities_name": "EnableGremlin"}, "Gremlin"), ({"capabilities_name": "EnableMongo"}, "MongoDB"),
    ({"capabilities_name": "EnableServerless"}, "NoSQL"),
])
def test_cosmosdb_account_rule(attributes, api):
    r = AZURE.resolve("azurerm_cosmosdb_account", attrs(**attributes))
    assert (r.icon, r.marked, r.decided_by) == ("azure:azure_cosmos_db", False, f"rule azurerm_cosmosdb_account api = {api}")


@pytest.mark.parametrize("missing", ["kind", "capabilities_name"])
def test_cosmosdb_account_unresolved_marks_and_keeps_base_icon(missing):
    r = AZURE.resolve("azurerm_cosmosdb_account", unresolved(missing))
    assert (r.icon, r.marked) == ("azure:azure_cosmos_db", True)


@pytest.mark.parametrize("tf_type", ["azapi_resource", "azapi_update_resource", "azapi_data_plane_resource"])
def test_azapi_resource_type_picks_the_arm_icon(tf_type):
    r = AZURE.resolve(tf_type, attrs(type="Microsoft.App/containerApps@2024-03-01"))
    assert (r.kind, r.icon, r.marked) == ("icon", "azure:worker_container_app", False)
    assert r.decided_by == f'rule {tf_type} type = "Microsoft.App/containerApps"'


def test_azapi_unknown_arm_type_is_none_and_marked():
    r = AZURE.resolve("azapi_resource", attrs(type="Microsoft.Nope/things@2024-01-01"))
    assert (r.kind, r.marked, r.reason) == ("none", True, "ARM type Microsoft.Nope/things not in arm_types")


def test_azapi_absent_type_is_none_and_marked():
    r = AZURE.resolve("azapi_resource", attrs())
    assert (r.kind, r.marked, r.reason) == ("none", True, "type is absent")


def test_azapi_unresolved_type_marks_and_keeps_the_generic_base():
    r = AZURE.resolve("azapi_resource", unresolved("type"))
    assert (r.kind, r.icon, r.marked, r.reason) == ("icon", "generic:generic_application", True, "type is not a literal")


def test_every_rule_icon_exists():
    for kind in ("OpenAI", "AIServices", "ContentModerator", "QnAMaker"):
        assert icons.known(AZURE.resolve("azurerm_cognitive_account", attrs(kind=kind)).icon)
    for attributes in ({"is_hns_enabled": "true"}, {"account_kind": "BlobStorage"}, {"account_kind": "FileStorage"}):
        assert icons.known(AZURE.resolve("azurerm_storage_account", attrs(**attributes)).icon)


def test_rules_only_apply_to_their_own_type_not_the_family():
    assert not AZURE.resolve("azurerm_lb_probe", unresolved("sku")).marked

