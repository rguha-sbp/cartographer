"""Azure trigger and route edge specs: which attribute names the source of an edge and which the destination."""
from cartographer.clouds.base import Spec

EVENT_ENDPOINTS = (
    "azure_function_endpoint", "storage_queue_endpoint", "eventhub_endpoint_id", "service_bus_queue_endpoint_id",
    "service_bus_topic_endpoint_id", "hybrid_connection_endpoint_id",
)
ACTION_GROUP_RECEIVERS = ("azure_function_receiver", "logic_app_receiver", "event_hub_receiver", "automation_runbook_receiver")
JOB = "stream_analytics_job_name"
STREAM_INPUTS = {
    "stream_input_eventhub": "eventhub_name", "stream_input_eventhub_v2": "eventhub_name",
    "stream_input_iothub": "iothub_namespace", "stream_input_blob": "storage_account_name",
    "reference_input_blob": "storage_account_name",
}
STREAM_OUTPUTS = {
    "output_blob": "storage_account_name", "output_table": "storage_account_name", "output_eventhub": "eventhub_name",
    "output_servicebus_queue": "servicebus_namespace", "output_servicebus_topic": "servicebus_namespace",
    "output_mssql": "server", "output_synapse": "server", "output_function": "function_app",
    "output_cosmosdb": "cosmosdb_sql_database_id",
}

EDGE_SPECS: dict[str, list[Spec]] = {
    "azurerm_eventgrid_event_subscription": [Spec("trigger", "scope", a) for a in EVENT_ENDPOINTS],
    "azurerm_eventgrid_system_topic_event_subscription": [Spec("trigger", "system_topic", a) for a in EVENT_ENDPOINTS],
    "azurerm_monitor_action_group": [Spec("trigger", None, a) for a in ACTION_GROUP_RECEIVERS],
    **{f"azurerm_stream_analytics_{kind}": [Spec("trigger", source, JOB)] for kind, source in STREAM_INPUTS.items()},
    **{f"azurerm_stream_analytics_{kind}": [Spec("trigger", JOB, sink)] for kind, sink in STREAM_OUTPUTS.items()},
    "azurerm_cdn_frontdoor_origin": [Spec("route", "cdn_frontdoor_origin_group_id", "host_name")],
    "azurerm_application_gateway": [Spec("route", None, "backend_address_pool")],
    "azurerm_api_management_backend": [Spec("route", "api_management_name", a) for a in ("url", "resource_id")],
    "azurerm_network_interface_backend_address_pool_association": [
        Spec("route", "backend_address_pool_id", "network_interface_id")],
}
