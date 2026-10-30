resource "aws_s3_bucket" "data" {
  bucket = "mini-data"
}

resource "aws_iam_role" "fn" {
  name = "mini-fn"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "fn_read" {
  name = "read-data"
  role = aws_iam_role.fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.data.arn}/*"
    }]
  })
}

resource "aws_lambda_function" "fn" {
  function_name = "mini-fn"
  role          = aws_iam_role.fn.arn
  handler       = "app.handler"
  runtime       = "python3.13"
  filename      = "app.zip"
}
