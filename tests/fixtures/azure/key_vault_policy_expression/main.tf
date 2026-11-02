variable "policies" {
  default = []
}

resource "azurerm_key_vault" "kv" {
  name          = "kv"
  access_policy = var.policies
}
