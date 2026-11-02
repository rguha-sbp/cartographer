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

resource "azurerm_subnet" "named_public" {
  name                 = "snet-public-web"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.182.0/24"]
}

resource "azurerm_subnet" "named_isolated" {
  name                 = "snet-isolated-data"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.172.0/24"]
}

resource "azurerm_subnet" "unnamed" {
  name                 = "snet-misc"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.21.0/24"]
}

resource "azurerm_subnet" "flag_on" {
  name                 = "snet-flag-on"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.54.0/24"]
  default_outbound_access_enabled = true
}

resource "azurerm_subnet" "tagged" {
  name                 = "x"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.v.name
  address_prefixes     = ["10.0.130.0/24"]
  tags = {
    Name = "tier-isolated"
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "named_public" {
  name                = "named_public"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.named_public.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "named_isolated" {
  name                = "named_isolated"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.named_isolated.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "unnamed" {
  name                = "unnamed"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.unnamed.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "flag_on" {
  name                = "flag_on"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.flag_on.id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "tagged" {
  name                = "tagged"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  network_interface {
    name    = "nic"
    primary = true
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.tagged.id
    }
  }
}
