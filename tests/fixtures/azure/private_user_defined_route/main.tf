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

resource "azurerm_subnet" "inline_route" {
  name                 = "inline_route"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.104.0/24"]
}

resource "azurerm_subnet" "separate_route" {
  name                 = "separate_route"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.64.0/24"]
}

resource "azurerm_subnet" "direct_route" {
  name                 = "direct_route"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.24.0/24"]
}

resource "azurerm_route_table" "inline" {
  name                = "inline"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  route {
    name                   = "default"
    address_prefix         = "0.0.0.0/0"
    next_hop_type          = "VirtualAppliance"
    next_hop_in_ip_address = "10.0.250.4"
  }
}

resource "azurerm_route_table" "separate" {
  name                = "separate"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_route" "default" {
  name                   = "default"
  resource_group_name    = azurerm_resource_group.rg.name
  route_table_name       = azurerm_route_table.separate.name
  address_prefix         = "0.0.0.0/0"
  next_hop_type          = "VirtualAppliance"
  next_hop_in_ip_address = "10.0.250.4"
}

resource "azurerm_route_table" "direct" {
  name                = "direct"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  route {
    name           = "default"
    address_prefix = "0.0.0.0/0"
    next_hop_type  = "Internet"
  }
}

resource "azurerm_subnet_route_table_association" "inline" {
  subnet_id      = azurerm_subnet.inline_route.id
  route_table_id = azurerm_route_table.inline.id
}

resource "azurerm_subnet_route_table_association" "separate" {
  subnet_id      = azurerm_subnet.separate_route.id
  route_table_id = azurerm_route_table.separate.id
}

resource "azurerm_subnet_route_table_association" "direct" {
  subnet_id      = azurerm_subnet.direct_route.id
  route_table_id = azurerm_route_table.direct.id
}

resource "azurerm_linux_virtual_machine_scale_set" "inline" {
  name                = "inline"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.inline_route.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "separate" {
  name                = "separate"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.separate_route.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "direct" {
  name                = "direct"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.direct_route.id
    }
  }
}
