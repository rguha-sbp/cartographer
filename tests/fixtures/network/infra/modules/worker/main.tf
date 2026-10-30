variable "vpc_id" {}
variable "subnet_ids" {}

resource "aws_security_group" "sg" {
  vpc_id = var.vpc_id
}

resource "aws_lambda_function" "fn" {
  function_name = "worker"

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.sg.id]
  }
}
