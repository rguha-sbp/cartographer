provider "azurerm" {
  features {}
  subscription_id = "11111111-1111-1111-1111-111111111111"
}

provider "azurerm" {
  alias           = "hub"
  features {}
  subscription_id = "22222222-2222-2222-2222-222222222222"
}

module "plain" {
  source = "Azure/avm-res-keyvault-vault/azurerm"
}

module "hub" {
  source    = "Azure/avm-res-keyvault-vault/azurerm"
  providers = { azurerm = azurerm.hub }
}
