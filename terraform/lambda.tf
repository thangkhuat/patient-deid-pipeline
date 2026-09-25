resource "aws_lambda_function" "pipeline" {
  function_name = "patient-deid-pipeline"
  role          = aws_iam_role.pipeline_lambda.arn
  handler       = "src.deid.lambda_handler.handler"
  runtime       = "python3.10"
  timeout       = 30
  memory_size   = 256

  filename         = "${path.module}/../pipeline_lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../pipeline_lambda.zip")

  environment {
    variables = {
      REDACTED_OUTPUT_BUCKET     = aws_s3_bucket.redacted_output.bucket
      REVIEW_ARTIFACTS_BUCKET    = aws_s3_bucket.review_artifacts.bucket
      REVIEW_ARTIFACTS_KMS_KEY_ID = aws_kms_key.review_artifacts.arn
    }
  }
}

resource "aws_lambda_permission" "allow_s3_input_notes" {
  statement_id  = "AllowS3InvokeFromInputNotes"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pipeline.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.input_notes.arn
}

resource "aws_s3_bucket_notification" "input_notes_trigger" {
  bucket = aws_s3_bucket.input_notes.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.pipeline.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_input_notes]
}

resource "aws_lambda_function" "upload_backend" {
  function_name = "patient-deid-upload-backend"
  role          = aws_iam_role.upload_backend.arn
  handler       = "src.deid.upload_handler.handler"
  runtime       = "python3.10"
  timeout       = 10
  memory_size   = 128

  filename         = "${path.module}/../upload_backend.zip"
  source_code_hash = filebase64sha256("${path.module}/../upload_backend.zip")

  environment {
    variables = {
      INPUT_NOTES_BUCKET = aws_s3_bucket.input_notes.bucket
    }
  }
}

resource "aws_lambda_function" "review_backend" {
  function_name = "patient-deid-review-backend"
  role          = aws_iam_role.review_backend.arn
  handler       = "src.deid.review_backend.handler"
  runtime       = "python3.10"
  timeout       = 15
  memory_size   = 256

  filename         = "${path.module}/../review_backend.zip"
  source_code_hash = filebase64sha256("${path.module}/../review_backend.zip")

  environment {
    variables = {
      REVIEW_ARTIFACTS_KMS_KEY_ID = aws_kms_key.review_artifacts.arn
    }
  }
}
