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

resource "azurerm_subnet" "agw" {
  name                 = "agw"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_public_ip" "pip" {
  name                = "pip"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
}

resource "azurerm_application_gateway" "g" {
  name                = "g"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  gateway_ip_configuration {
    name      = "gw"
    subnet_id = azurerm_subnet.agw.id
  }
  frontend_ip_configuration {
    name                 = "public"
    public_ip_address_id = azurerm_public_ip.pip.id
  }
  frontend_ip_configuration {
    name                 = "private"
    subnet_id            = azurerm_subnet.agw.id
    private_ip_address   = "10.0.1.10"
  }
}
