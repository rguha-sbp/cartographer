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

resource "azurerm_linux_web_app" "worker" {
  name                = "worker"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_key_vault" "kv" {
  name                = "kv"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location

  access_policy {
    tenant_id          = azurerm_linux_web_app.app.identity[0].tenant_id
    object_id          = azurerm_linux_web_app.app.identity[0].principal_id
    secret_permissions = ["Get", "List"]
    key_permissions    = ["Get"]
  }

  access_policy {
    tenant_id          = azurerm_linux_web_app.worker.identity[0].tenant_id
    object_id          = azurerm_linux_web_app.worker.identity[0].principal_id
    secret_permissions = ["Get"]
  }
}
