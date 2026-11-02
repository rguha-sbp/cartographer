resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

resource "azurerm_storage_account" "sa" {
  name                = "sa"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_linux_function_app" "fn" {
  name                = "fn"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_eventgrid_event_subscription" "blob_created" {
  name  = "blob-created"
  scope = azurerm_storage_account.sa.id
  azure_function_endpoint {
    function_id = "${azurerm_linux_function_app.fn.id}/functions/handler"
  }
}

resource "azurerm_monitor_action_group" "ops" {
  name                = "ops"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "ops"
  azure_function_receiver {
    name                     = "fn"
    function_app_resource_id = azurerm_linux_function_app.fn.id
    function_name            = "handler"
    http_trigger_url         = "https://example.invalid"
    use_common_alert_schema  = true
  }
}

resource "azurerm_linux_web_app" "app" {
  name                = "app"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_cdn_frontdoor_profile" "fd" {
  name                = "fd"
  resource_group_name = azurerm_resource_group.rg.name
  sku_name            = "Standard_AzureFrontDoor"
}

resource "azurerm_cdn_frontdoor_origin_group" "g" {
  name                     = "g"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.fd.id
}

resource "azurerm_cdn_frontdoor_origin" "o" {
  name                          = "o"
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.g.id
  host_name                     = azurerm_linux_web_app.app.default_hostname
  certificate_name_check_enabled = true
}

resource "azurerm_application_gateway" "gw" {
  name                = "gw"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  backend_address_pool {
    name  = "app"
    fqdns = [azurerm_linux_web_app.app.default_hostname]
  }
}

resource "azurerm_stream_analytics_job" "job" {
  name                = "job"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_eventhub" "events" {
  name = "events"
}

resource "azurerm_stream_analytics_stream_input_eventhub" "in" {
  name                      = "in"
  stream_analytics_job_name = azurerm_stream_analytics_job.job.name
  resource_group_name       = azurerm_resource_group.rg.name
  eventhub_name             = azurerm_eventhub.events.name
}

resource "azurerm_stream_analytics_output_blob" "out" {
  name                      = "out"
  stream_analytics_job_name = azurerm_stream_analytics_job.job.name
  resource_group_name       = azurerm_resource_group.rg.name
  storage_account_name      = azurerm_storage_account.sa.name
}
