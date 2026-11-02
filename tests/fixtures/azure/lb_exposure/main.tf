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

resource "azurerm_subnet" "edge" {
  name                 = "edge"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_subnet" "back" {
  name                 = "back"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.2.0/24"]
}

resource "azurerm_subnet" "gw" {
  name                 = "gw"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.3.0/24"]
}

resource "azurerm_public_ip" "ip" {
  name                = "ip"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
}

resource "azurerm_public_ip_prefix" "prefix" {
  name                = "prefix"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_lb" "public_ip" {
  name                = "a"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Standard"
  frontend_ip_configuration {
    name                 = "f"
    public_ip_address_id = azurerm_public_ip.ip.id
  }
}

resource "azurerm_lb" "public_prefix" {
  name                = "b"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  frontend_ip_configuration {
    name                = "f"
    public_ip_prefix_id = azurerm_public_ip_prefix.prefix.id
  }
}

resource "azurerm_lb" "internal" {
  name                = "c"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  frontend_ip_configuration {
    name      = "f"
    subnet_id = azurerm_subnet.back.id
  }
}

resource "azurerm_lb" "internal_private_ip" {
  name                = "d"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  frontend_ip_configuration {
    name               = "f"
    private_ip_address = "10.0.2.10"
  }
}

resource "azurerm_lb" "no_frontend" {
  name                = "e"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_lb" "second_frontend_public" {
  name                = "f"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  frontend_ip_configuration {
    name      = "i"
    subnet_id = azurerm_subnet.back.id
  }
  frontend_ip_configuration {
    name                 = "p"
    public_ip_address_id = azurerm_public_ip.ip.id
  }
}

resource "azurerm_application_gateway" "gw" {
  name                = "gw"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku {
    name = "Standard_v2"
    tier = "Standard_v2"
  }
  gateway_ip_configuration {
    name      = "g"
    subnet_id = azurerm_subnet.gw.id
  }
  frontend_ip_configuration {
    name                 = "f"
    public_ip_address_id = azurerm_public_ip.ip.id
  }
}

resource "azurerm_network_interface" "nic_prefixless" {
  name                = "nic"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  ip_configuration {
    name                          = "ip"
    subnet_id                     = azurerm_subnet.edge.id
    public_ip_address_id          = azurerm_public_ip.ip.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "vm" {
  name                  = "vm"
  resource_group_name   = azurerm_resource_group.rg.name
  location              = azurerm_resource_group.rg.location
  network_interface_ids = [azurerm_network_interface.nic_prefixless.id]
}
