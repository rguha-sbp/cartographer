resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

resource "azurerm_key_vault" "kv" {
  name                = "kv"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_linux_web_app" "app" {
  name                = "app"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_key_vault_access_policy" "app" {
  key_vault_id       = azurerm_key_vault.kv.id
  tenant_id          = azurerm_linux_web_app.app.identity[0].tenant_id
  object_id          = azurerm_linux_web_app.app.identity[0].principal_id
  secret_permissions = ["Get", "List"]
  key_permissions    = ["Get"]
}
