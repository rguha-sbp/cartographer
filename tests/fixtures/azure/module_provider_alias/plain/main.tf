variable "region" {
  type    = string
  default = "westeurope"
}

resource "azurerm_storage_account" "sa" {
  name                = "sa"
  resource_group_name = "rg"
  location            = var.region
}
