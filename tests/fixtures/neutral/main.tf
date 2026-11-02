variable "lb_kind" {}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_cloudwatch_log_group" "fn" {
  name = "/aws/lambda/fn-${random_id.suffix.hex}"
}

resource "aws_lambda_function" "fn" {
  function_name = "fn"
  role          = "arn:aws:iam::1:role/x"
  depends_on    = [aws_cloudwatch_log_group.fn]
  environment {
    variables = { LOG_GROUP = aws_cloudwatch_log_group.fn.name }
  }
}

resource "aws_lb" "front" {
  load_balancer_type = var.lb_kind
}

resource "kubernetes_namespace" "apps" {
  metadata {
    name = "apps"
  }
}
