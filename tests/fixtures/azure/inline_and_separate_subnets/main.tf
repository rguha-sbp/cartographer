resource "azurerm_virtual_network" "inl" {
  name          = "inl"
  location      = "westeurope"
  address_space = ["10.1.0.0/16"]
  subnet {
    name             = "snet-isolated-a"
    address_prefixes = ["10.1.1.0/24"]
  }
}

resource "azurerm_virtual_network" "sep" {
  name          = "sep"
  location      = "westeurope"
  address_space = ["10.2.0.0/16"]
}

resource "azurerm_subnet" "b" {
  name                 = "snet-public-b"
  resource_group_name  = "rg"
  virtual_network_name = azurerm_virtual_network.sep.name
  address_prefixes     = ["10.2.1.0/24"]
}

resource "azurerm_linux_virtual_machine_scale_set" "inl" {
  name = "inl"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = tolist(azurerm_virtual_network.inl.subnet)[0].id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "sep" {
  name = "sep"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_subnet.b.id
    }
  }
}
