resource "azurerm_virtual_network" "hub" {
  name          = "hub"
  location      = "westeurope"
  address_space = ["10.0.0.0/16", "10.10.0.0/16"]
}

resource "azurerm_virtual_network" "spoke" {
  name          = "spoke"
  location      = "westeurope"
  address_space = ["10.1.0.0/16"]
}

resource "azurerm_virtual_network_peering" "hub_to_spoke" {
  name                      = "hub-to-spoke"
  resource_group_name       = "rg"
  virtual_network_name      = azurerm_virtual_network.hub.name
  remote_virtual_network_id = azurerm_virtual_network.spoke.id
}

resource "azurerm_virtual_network_peering" "spoke_to_hub" {
  name                      = "spoke-to-hub"
  resource_group_name       = "rg"
  virtual_network_name      = azurerm_virtual_network.spoke.name
  remote_virtual_network_id = azurerm_virtual_network.hub.id
}

variable "cidr" {
  type = string
}

resource "azurerm_virtual_network" "dynamic" {
  name          = "dynamic"
  location      = "westeurope"
  address_space = [var.cidr]
}
