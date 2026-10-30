data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/../src/app"
  output_path = "app.zip"
}

resource "aws_lambda_function" "app" {
  function_name = "app"
  role          = "arn:aws:iam::123456789012:role/app"
  handler       = "app.handler"
  runtime       = "python3.13"
  filename      = data.archive_file.app.output_path
}

resource "aws_ssm_parameter" "stripe_key" {
  name  = "/app/stripe/key"
  type  = "SecureString"
  value = "REDACTED"
}

variable "billing_url" {
  default = "https://billing.vendor.example.org/v2"
}

module "acme_publisher" {
  source = "./modules/pub"
  name   = "acme"
}
