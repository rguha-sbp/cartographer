variable "subnets" {
  default = []
}

resource "azurerm_virtual_network" "v" {
  name          = "v"
  address_space = ["10.0.0.0/16"]
  subnet        = var.subnets
}

resource "azurerm_route_table" "rt" {
  name  = "rt"
  route = var.subnets
}

resource "azurerm_lb" "lb" {
  name                      = "lb"
  frontend_ip_configuration = var.subnets
}

resource "azurerm_private_endpoint" "pe" {
  name      = "pe"
  subnet_id = azurerm_virtual_network.v.subnet[0].id
}
