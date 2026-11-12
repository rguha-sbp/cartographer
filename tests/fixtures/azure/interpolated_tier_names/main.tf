variable "env" { default = "dev" }
resource "azurerm_virtual_network" "v" {
  name = "v"
  location = "westeurope"
  resource_group_name = "rg"
  address_space = ["10.0.0.0/16"]
}
resource "azurerm_subnet" "a" {
  name = "snet-${var.env}-public"
  resource_group_name = "rg"
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes = ["10.0.1.0/24"]
}
resource "azurerm_subnet" "b" {
  name = "${var.env}-isolated"
  resource_group_name = "rg"
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes = ["10.0.2.0/24"]
}
resource "azurerm_private_endpoint" "pa" {
  name = "x"
  location = "westeurope"
  resource_group_name = "rg"
  subnet_id = azurerm_subnet.a.id
}
resource "azurerm_private_endpoint" "pb" {
  name = "y"
  location = "westeurope"
  resource_group_name = "rg"
  subnet_id = azurerm_subnet.b.id
}
resource "azurerm_subnet" "c" {
  name = format("snet-%s-public", var.env)
  resource_group_name = "rg"
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes = ["10.0.3.0/24"]
}
resource "azurerm_private_endpoint" "pc" {
  name = "z"
  location = "westeurope"
  resource_group_name = "rg"
  subnet_id = azurerm_subnet.c.id
}
