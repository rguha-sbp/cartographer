variable "name" {}

resource "aws_lambda_function" "fn" {
  function_name = "${var.name}-publisher"
  role          = "arn:aws:iam::123456789012:role/pub"
  s3_bucket     = "artifacts"
  s3_key        = "pub.zip"
}
