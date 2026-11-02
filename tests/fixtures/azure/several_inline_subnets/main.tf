resource "azurerm_virtual_network" "v" {
  name          = "v"
  location      = "westeurope"
  address_space = ["10.3.0.0/16"]
  subnet {
    name             = "snet-public-a"
    address_prefixes = ["10.3.1.0/24"]
  }
  subnet {
    name             = "snet-isolated-b"
    address_prefixes = ["10.3.2.0/24"]
  }
  subnet {
    name             = "snet-c"
    address_prefixes = ["10.3.3.0/24"]
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "by_name" {
  name = "by_name"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = [for s in azurerm_virtual_network.v.subnet : s.id if s.name == "snet-isolated-b"][0]
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "by_prefix" {
  name = "by_prefix"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = [for s in azurerm_virtual_network.v.subnet : s.id if contains(s.address_prefixes, "10.3.1.0/24")][0]
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "ambiguous" {
  name = "ambiguous"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = azurerm_virtual_network.v.subnet[*].id
    }
  }
}

resource "azurerm_linux_virtual_machine_scale_set" "unknown_name" {
  name = "unknown_name"
  network_interface {
    name = "nic"
    ip_configuration {
      name      = "ip"
      subnet_id = [for s in azurerm_virtual_network.v.subnet : s.id if s.name == "snet-missing"][0]
    }
  }
}
