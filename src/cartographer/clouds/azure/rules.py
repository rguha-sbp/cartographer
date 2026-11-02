"""Attribute rules: a catalog row names one, and it picks the icon from the resource's own literal attributes.
Returning None keeps the row's icon. An attribute that is not a literal is handled by Cloud.resolve, not here.
Every rule reads all of its attributes before deciding, so an unresolved one always marks the base icon."""

import json
from pathlib import Path

from cartographer.clouds.base import Getter, Resolution, Rule

ARM_TYPES: dict[str, str] = {k.lower(): v for k, v in json.loads((Path(__file__).parent / "arm_types.json").read_text()).items()}

# The pinned icon set has one icon each for load balancers, application gateways and Cosmos DB, so those rules
# keep the icon and record whether the frontend is public or internal, which tier or which API the attributes name.
COGNITIVE_KINDS = {
    "OpenAI": "azure_openai", "AIServices": "ai_foundry", "SpeechServices": "speech_services",
    "FormRecognizer": "form_recognizers", "ComputerVision": "computer_vision", "Face": "face_apis",
    "TextAnalytics": "language_services", "ContentSafety": "content_safety", "TextTranslation": "translator_text",
    "LUIS": "language_understanding", "ContentModerator": "content_moderators", "QnAMaker": "qna_makers",
}
COSMOS_CAPABILITIES = {"EnableCassandra": "Cassandra", "EnableTable": "Table", "EnableGremlin": "Gremlin", "EnableMongo": "MongoDB"}


def arm_icon(arm_type: str) -> str | None:
    return ARM_TYPES.get(arm_type.split("@", 1)[0].lower())


FRONTEND = "frontend_ip_configuration"
# Listed public first: a load balancer with any public frontend is public.
LB_FRONTENDS = (("public_ip_address_id", "public"), ("public_ip_prefix_id", "public"),
                ("subnet_id", "internal"), ("private_ip_address", "internal"))


def _lb(get: Getter) -> Resolution:
    for attr, exposure in LB_FRONTENDS:
        if get(f"{FRONTEND}.{attr}", present=True):
            return Resolution("icon", "azure:load_balancers", f"rule azurerm_lb frontend {attr} set ({exposure})")
    return Resolution("icon", "azure:load_balancers", f"rule azurerm_lb {FRONTEND} absent", marked=True,
                      reason=f"{FRONTEND} absent")


def _application_gateway(get: Getter) -> Resolution:
    tier = get("sku.tier")
    if tier is None:
        note = "sku.tier absent"
    else:
        waf = " (web application firewall)" if str(tier).startswith("WAF") else ""
        note = f'sku.tier = "{tier}"{waf}'
    return Resolution("icon", "azure:application_gateways", f"rule azurerm_application_gateway {note}")


def _cognitive_account(get: Getter) -> Resolution:
    kind = get("kind")
    icon = COGNITIVE_KINDS.get(kind, "cognitive_services") if isinstance(kind, str) else "cognitive_services"
    return Resolution("icon", f"azure:{icon}", f'rule azurerm_cognitive_account kind = "{kind}"')


def _storage_account(get: Getter) -> Resolution | None:
    hns, kind = get("is_hns_enabled"), get("account_kind")
    if str(hns).lower() == "true":
        return Resolution("icon", "azure:data_lake_storage_gen1", "rule azurerm_storage_account is_hns_enabled = true")
    if kind == "BlobStorage":
        return Resolution("icon", "azure:blob_block", 'rule azurerm_storage_account account_kind = "BlobStorage"')
    if kind == "FileStorage":
        return Resolution("icon", "azure:storage_azure_files", 'rule azurerm_storage_account account_kind = "FileStorage"')
    return None


def _cosmosdb_account(get: Getter) -> Resolution:
    kind, capability = get("kind"), get("capabilities.name")
    api = COSMOS_CAPABILITIES.get(capability) if isinstance(capability, str) else None
    api = api or ("MongoDB" if kind == "MongoDB" else "NoSQL")
    return Resolution("icon", "azure:azure_cosmos_db", f"rule azurerm_cosmosdb_account api = {api}")


def _azapi(tf_type: str) -> Rule:
    def rule(get: Getter) -> Resolution:
        arm_type = get("type")
        if not isinstance(arm_type, str):
            return Resolution("none", marked=True, reason="type is absent", decided_by=f"rule {tf_type} type absent")
        name = arm_type.split("@", 1)[0]
        icon = arm_icon(arm_type)
        if icon is None:
            return Resolution("none", marked=True, reason=f"ARM type {name} not in arm_types",
                              decided_by=f"rule {tf_type} type not in arm_types")
        return Resolution("icon", f"azure:{icon}", f'rule {tf_type} type = "{name}"')

    return rule


RULES: dict[str, Rule] = {
    "azurerm_lb": _lb,
    "azurerm_application_gateway": _application_gateway,
    "azurerm_cognitive_account": _cognitive_account,
    "azurerm_storage_account": _storage_account,
    "azurerm_cosmosdb_account": _cosmosdb_account,
    **{t: _azapi(t) for t in ("azapi_resource", "azapi_update_resource", "azapi_data_plane_resource")},
}
