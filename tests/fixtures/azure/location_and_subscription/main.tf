provider "azurerm" {
  features {}
  subscription_id = "11111111-1111-1111-1111-111111111111"
}

provider "azurerm" {
  alias           = "hub"
  features {}
  subscription_id = "22222222-2222-2222-2222-222222222222"
}

provider "azurerm" {
  alias           = "dynamic"
  features {}
  subscription_id = var.subscription
}

variable "subscription" {
  type = string
}

variable "region" {
  type    = string
  default = "swedencentral"
}

variable "unset_region" {
  type = string
}

resource "azurerm_resource_group" "rg" {
  name     = "rg"
  location = "westeurope"
}

resource "azurerm_storage_account" "via_group" {
  name                = "via-group"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_storage_account" "literal" {
  name                = "literal"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "northeurope"
}

resource "azurerm_storage_account" "from_variable" {
  name                = "from-variable"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.region
}

resource "azurerm_storage_account" "unknown" {
  name                = "unknown"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.unset_region
}

resource "azurerm_storage_account" "hub" {
  provider            = azurerm.hub
  name                = "hub"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

resource "azurerm_storage_account" "dynamic" {
  provider            = azurerm.dynamic
  name                = "dynamic"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}
