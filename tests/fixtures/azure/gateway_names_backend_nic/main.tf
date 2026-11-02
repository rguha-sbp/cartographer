resource "azurerm_virtual_network" "v" {
  name = "v"
  address_space = ["10.0.0.0/16"]
}
resource "azurerm_subnet" "agw" {
  name = "agw"
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes = ["10.0.1.0/24"]
}
resource "azurerm_subnet" "app" {
  name = "app"
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes = ["10.0.2.0/24"]
}
resource "azurerm_public_ip" "pip" {
  name = "p"
}
resource "azurerm_network_interface" "vm" {
  name = "n"
  ip_configuration {
    name = "i"
    subnet_id = azurerm_subnet.app.id
  }
}
resource "azurerm_linux_virtual_machine" "vm" {
  name = "vm"
  network_interface_ids = [azurerm_network_interface.vm.id]
}
resource "azurerm_application_gateway" "gw" {
  name = "g"
  sku { tier = "Standard_v2" }
  gateway_ip_configuration {
    name = "x"
    subnet_id = azurerm_subnet.agw.id
  }
  frontend_ip_configuration {
    name = "pub"
    public_ip_address_id = azurerm_public_ip.pip.id
  }
  backend_address_pool {
    name = "b"
    ip_addresses = [azurerm_network_interface.vm.private_ip_address]
  }
}
