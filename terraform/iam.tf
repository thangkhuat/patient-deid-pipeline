resource "aws_iam_role" "pipeline_lambda" {
  name = "patient-deid-pipeline-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_lambda_read_input_notes" {
  name = "read-input-notes"
  role = aws_iam_role.pipeline_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.input_notes.arn}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_lambda_write_redacted_output" {
  name = "write-redacted-output"
  role = aws_iam_role.pipeline_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.redacted_output.arn}/*" }
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_lambda_write_review_artifacts" {
  name = "write-review-artifacts"
  role = aws_iam_role.pipeline_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.review_artifacts.arn}/*" }
    ]
  })
}

resource "aws_iam_role" "upload_backend" {
  name = "patient-deid-upload-backend"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "upload_backend_write_input_notes" {
  name = "write-input-notes"
  role = aws_iam_role.upload_backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.input_notes.arn}/*" },
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_lambda_logging" {
  name = "write-logs"
  role = aws_iam_role.pipeline_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "logs:CreateLogGroup"
        Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/patient-deid-pipeline:*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "pipeline_lambda_detect_phi" {
  name = "detect-phi"
  role = aws_iam_role.pipeline_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "comprehendmedical:DetectPHI", Resource = "*" }
    ]
  })
}

resource "aws_iam_user" "reviewer_test" {
  name = "patient-deid-reviewer-cli"
}

resource "aws_iam_user_policy" "reviewer_test_read_review_artifacts" {
  name = "read-review-artifacts"
  user = aws_iam_user.reviewer_test.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:GetObject", Resource = "${aws_s3_bucket.review_artifacts.arn}/*" }
    ]
  })
}

resource "aws_iam_role_policy" "upload_backend_logging" {
  name = "write-logs"
  role = aws_iam_role.upload_backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "logs:CreateLogGroup"
        Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/patient-deid-upload-backend:*"
      }
    ]
  })
}

resource "aws_iam_user_policy" "reviewer_test_list_review_artifacts" {
  name = "list-review-artifacts"
  user = aws_iam_user.reviewer_test.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.review_artifacts.arn }
    ]
  })
}

resource "aws_iam_role" "review_backend" {
  name = "patient-deid-review-backend"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }
    ]
  })
}

resource "aws_iam_role_policy" "review_backend_logging" {
  name = "write-logs"
  role = aws_iam_role.review_backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "logs:CreateLogGroup", Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:*" },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:ap-southeast-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/patient-deid-review-backend:*" }
    ]
  })
}

resource "aws_iam_role_policy" "review_backend_read_review_artifacts" {
  name = "read-review-artifacts"
  role = aws_iam_role.review_backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.review_artifacts.arn },
      { Effect = "Allow", Action = "s3:GetObject", Resource = "${aws_s3_bucket.review_artifacts.arn}/*" }
    ]
  })
}