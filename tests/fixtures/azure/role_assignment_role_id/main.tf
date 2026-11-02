resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

resource "azurerm_linux_web_app" "app" {
  name                = "app"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "by_id" {
  scope              = azurerm_resource_group.rg.id
  role_definition_id = "/subscriptions/s/providers/Microsoft.Authorization/roleDefinitions/r"
  principal_id       = azurerm_linux_web_app.app.identity[0].principal_id
}
