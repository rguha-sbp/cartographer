from cartographer.clouds.azure.network import network_facts
from cartographer.clouds.azure.rules import RULES
from cartographer.clouds.base import Catalog, Cloud, load_json
from cartographer.diagram_model import FRAME_TITLE_LEFT


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

    def icon_style(self, name: str) -> str:
        return (f"image;aspect=fixed;html=1;points=[];align=center;fontSize=12;"
                f"image=img/lib/azure2/{self.icons[name]['path']};verticalLabelPosition=bottom;verticalAlign=top;")


AZURE = AzureCloud(
    "azure", "Azure", ("azurerm", "azapi"), load_json(__file__, "icons.json"), FRAME_STYLES, "Azure managed services",
    provider_types=load_json(__file__, "provider_types.json"), catalog=Catalog(load_json(__file__, "catalog.json")),
    rules=RULES, modules=load_json(__file__, "modules.json"), network_attrs=NETWORK_ATTRS,
)
