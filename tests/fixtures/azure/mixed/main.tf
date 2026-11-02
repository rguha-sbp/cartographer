resource "aws_s3_bucket" "logs" {
  bucket = "logs"
}

resource "azurerm_storage_account" "data" {
  name     = "data"
  location = "westeurope"
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "random_password" "admin" {
  length = 24
}

resource "kubernetes_namespace" "apps" {
  metadata {
    name = "apps"
  }
}

module "vault" {
  source = "Azure/avm-res-keyvault-vault/azurerm"
  name   = "vault-${random_id.suffix.hex}"
}

module "landing_zone" {
  source = "Azure/avm-ptn-alz/azurerm"
}
