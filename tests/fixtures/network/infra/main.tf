locals {
  shop_cidr = "10.30.0.0/16"
}

variable "spare_cidr" {
  default = "10.99.0.0/16"
}

variable "dyn_cidr" {}

resource "aws_vpc" "main" {
  cidr_block = local.shop_cidr
}

resource "aws_vpc_ipv4_cidr_block_association" "extra" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.31.0.0/20"
}

resource "aws_vpc" "dyn" {
  cidr_block = var.dyn_cidr
}

resource "aws_vpc" "spare" {
  cidr_block = var.spare_cidr
}

resource "aws_subnet" "front" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.30.0.0/24"
  map_public_ip_on_launch = true
}

resource "aws_subnet" "orders" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.30.1.0/24"
  tags       = { Name = "shop-orders-private" }
}

resource "aws_subnet" "ledger" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.30.2.0/24"
  tags       = { Name = "shop-ledger-isolated" }
}

resource "aws_subnet" "plain" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.30.3.0/24"
}

resource "aws_lb" "front" {
  subnets = [aws_subnet.front.id]
}

resource "aws_instance" "orders" {
  subnet_id = aws_subnet.orders.id
}

resource "aws_db_instance" "ledger" {
  db_subnet_group_name = "x"
  vpc_security_group_ids = []
  subnet_id            = aws_subnet.ledger.id
}

resource "aws_instance" "misc" {
  subnet_id = aws_subnet.plain.id
}

resource "aws_route_table_association" "front" {
  subnet_id = aws_subnet.front.id
}

resource "aws_instance" "lost" {
  subnet_id = data.tfe_outputs.networking.nonsensitive_values.shared_vpc_subnet_ids
}

resource "aws_instance" "outside" {
  subnet_id = data.tfe_outputs.networking.nonsensitive_values.other_vpc_private_subnet_ids
}

module "worker" {
  source     = "./modules/worker"
  vpc_id     = data.tfe_outputs.networking.nonsensitive_values.shared_vpc_id
  subnet_ids = data.tfe_outputs.networking.nonsensitive_values.shared_vpc_private_subnet_ids
}
