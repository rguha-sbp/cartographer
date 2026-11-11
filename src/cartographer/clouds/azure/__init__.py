import re

from cartographer.clouds.azure.network import network_facts
from cartographer.clouds.azure.permissions import permission_edges
from cartographer.clouds.azure.rules import RULES
from cartographer.clouds.azure.specs import EDGE_SPECS
from cartographer.clouds.base import Catalog, Cloud, load_json
from cartographer.diagram_model import FRAME_TITLE_LEFT
from cartographer.tf_policies import unq
from cartographer.tf_values import text

ALIAS = re.compile(r"\b(?:azurerm|azapi)\.(\w+)")


def _frame(kind: str, stroke: str, font: str, dashed: int) -> str:
    # draw.io ignores grIcon on a plain rectangle; the diagram reader identifies a frame kind by it
    return (f"grIcon=azure_{kind};rounded=1;arcSize=2;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;container=1;pointerEvents=0;"
            f"collapsible=0;recursiveResize=0;fillColor=none;strokeColor={stroke};fontColor={font};dashed={dashed};"
            f"verticalAlign=top;align=left;spacingLeft={FRAME_TITLE_LEFT};")


FRAME_STYLES = {
    "cloud": _frame("cloud", "#0078D4", "#0078D4", 0),
    "region": _frame("region", "#5E5E5E", "#5E5E5E", 1),
    "account": _frame("account", "#50E6FF", "#005BA1", 0),
    "network": _frame("network", "#0078D4", "#005BA1", 0),
    "subnet-public": _frame("subnet", "#57A300", "#3B7A00", 0),
    "subnet-private": _frame("subnet", "#0078D4", "#005BA1", 0),
    "subnet-isolated": _frame("subnet", "#0078D4", "#005BA1", 1),
}


# Nested blocks are named too: the extractor only sees top-level attributes of a resource
NETWORK_ATTRS = frozenset({
    "subnet_id", "subnet_ids", "virtual_network_subnet_id", "delegated_subnet_id", "infrastructure_subnet_id",
    "virtual_network_id", "remote_virtual_network_id", "virtual_network_name", "ip_configuration", "default_node_pool",
    "virtual_network_configuration", "gateway_ip_configuration", "network_interface",
})


class AzureCloud(Cloud):
    def network_facts(self, ex):
        return network_facts(ex)

    def permission_edges(self, ex):
        permission_edges(ex)

    def extra(self, ex, res):
        return {"location": self.location(ex, res), "subscription": self.subscription(ex, res)}

    @staticmethod
    def location(ex, res):
        """The literal location, or the literal location of the resource group it references."""
        expr = res.block.body.get("location")
        found = res.inst.value(expr)
        if isinstance(found, str):
            return found
        for address in sorted(ex.refs(res.inst, expr)):
            group = ex.by_address.get(address)
            literal = group.inst.value(group.block.body.get("location")) if group and group.type == "azurerm_resource_group" else None
            if isinstance(literal, str):
                return literal
        return None

    @staticmethod
    def subscription(ex, res):
        """The `subscription_id` literal of the provider block the resource uses, by alias; None when it is not one."""
        body = res.block.body
        if res.type == "module":
            provider, mapped = "azurerm", body.get("providers")
            chosen = next((v for k, v in mapped.items() if unq(k) == provider), "") if isinstance(mapped, dict) else ""
        else:
            provider, chosen = res.type.split("_", 1)[0], body.get("provider", "")
        alias = ALIAS.search(text(chosen))
        key = f"{provider}.{alias[1]}" if alias else provider
        inst = res.inst
        while inst is not None and key not in inst.mod.providers:
            key = inst.provider_map.get(key, key)
            inst = inst.parent
        if not key:
            return None
        found = inst.value(inst.mod.providers[key].get("subscription_id")) if inst else None
        return found if isinstance(found, str) else None

    def icon_style(self, name: str) -> str:
        return (f"image;aspect=fixed;html=1;points=[];align=center;fontSize=12;"
                f"image=img/lib/azure2/{self.icons[name]['path']};verticalLabelPosition=bottom;verticalAlign=top;")


AZURE = AzureCloud(
    "azure", "Azure", ("azurerm", "azapi"), load_json(__file__, "icons.json"), FRAME_STYLES, "Azure managed services",
    provider_types=load_json(__file__, "provider_types.json"), catalog=Catalog(load_json(__file__, "catalog.json")),
    rules=RULES, modules=load_json(__file__, "modules.json"), edge_specs=EDGE_SPECS, network_attrs=NETWORK_ATTRS,
    deployed_types=frozenset({
        "azurerm_linux_function_app", "azurerm_windows_function_app", "azurerm_linux_web_app", "azurerm_windows_web_app",
        "azurerm_container_app", "azurerm_kubernetes_cluster", "azurerm_linux_virtual_machine",
        "azurerm_windows_virtual_machine", "azurerm_linux_virtual_machine_scale_set",
        "azurerm_windows_virtual_machine_scale_set", "azurerm_mssql_database", "azurerm_postgresql_flexible_server",
        "azurerm_mysql_flexible_server", "azurerm_cosmosdb_account", "azurerm_storage_account",
        "azurerm_servicebus_queue", "azurerm_servicebus_topic", "azurerm_eventhub", "azurerm_redis_cache",
    }),
)
