data "tfe_outputs" "net" {
  organization = "o"
  workspace = "w"
}
resource "azurerm_subnet" "extra" {
  name = "extra"
  resource_group_name = "rg"
  virtual_network_name = data.tfe_outputs.net.nonsensitive_values.hub_vnet_name
  address_prefixes = ["10.0.9.0/24"]
}
resource "azurerm_private_endpoint" "pa" {
  name = "x"
  location = "westeurope"
  resource_group_name = "rg"
  subnet_id = data.tfe_outputs.net.nonsensitive_values.hub_vnet_private_subnet_id
}
