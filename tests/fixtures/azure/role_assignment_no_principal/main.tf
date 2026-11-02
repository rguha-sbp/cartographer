resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "pipeline" {
  scope                = azurerm_resource_group.rg.id
  role_definition_name = "Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}
