resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

resource "azurerm_virtual_network" "v" {
  name                = "v"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "workers" {
  name                 = "workers"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.54.0/24"]
}

resource "azurerm_linux_virtual_machine_scale_set" "workers" {
  name                = "workers"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.workers.id
    }
  }
}
