data "aws_iam_openid_connect_provider" "github_actions" {
  arn = "arn:aws:iam::471116065597:oidc-provider/token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions_frontend_deploy" {
  name = "patient-deid-github-actions-frontend-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = data.aws_iam_openid_connect_provider.github_actions.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:thangkhuat/patient-deid-pipeline:ref:refs/heads/main",
              "repo:thangkhuat@177017208/patient-deid-pipeline@1327731147:ref:refs/heads/main"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_frontend_deploy_write" {
  name = "write-frontend"
  role = aws_iam_role.github_actions_frontend_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.frontend.arn}/*" },
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.frontend.arn },
      { Effect = "Allow", Action = "cloudfront:CreateInvalidation", Resource = aws_cloudfront_distribution.frontend.arn }
    ]
  })
}

resource "aws_iam_role" "github_actions_lambda_deploy" {
  name = "patient-deid-github-actions-lambda-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = data.aws_iam_openid_connect_provider.github_actions.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:thangkhuat/patient-deid-pipeline:ref:refs/heads/main",
              "repo:thangkhuat@177017208/patient-deid-pipeline@1327731147:ref:refs/heads/main"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_lambda_deploy_update_code" {
  name = "update-lambda-code"
  role = aws_iam_role.github_actions_lambda_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:UpdateFunctionCode"
        Resource = [
          aws_lambda_function.pipeline.arn,
          aws_lambda_function.upload_backend.arn,
          aws_lambda_function.review_backend.arn,
        ]
      }
    ]
  })
}
