data "azurerm_virtual_network" "hub" {
  name                = "hub"
  resource_group_name = "rg"
}

resource "azurerm_virtual_network" "spoke" {
  name          = "spoke"
  location      = "westeurope"
  address_space = ["10.1.0.0/16"]
}

resource "azurerm_virtual_network_peering" "to_hub" {
  name                      = "to-hub"
  resource_group_name       = "rg"
  virtual_network_name      = azurerm_virtual_network.spoke.name
  remote_virtual_network_id = data.azurerm_virtual_network.hub.id
}

resource "azurerm_virtual_network_peering" "to_shared" {
  name                      = "to-shared"
  resource_group_name       = "rg"
  virtual_network_name      = azurerm_virtual_network.spoke.name
  remote_virtual_network_id = data.tfe_outputs.net.nonsensitive_values.shared_vnet_id
}

resource "azurerm_linux_virtual_machine_scale_set" "w" {
  name = "w"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = data.tfe_outputs.net.nonsensitive_values.shared_vnet_private_subnet_id
    }
  }
}
