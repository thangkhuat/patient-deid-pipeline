resource "aws_apigatewayv2_api" "upload" {
  name          = "patient-deid-upload-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["https://d2tno7uvqes2o4.cloudfront.net"]
    allow_methods = ["POST"]
    allow_headers = ["content-type", "authorization"]
  }
}

resource "aws_apigatewayv2_integration" "upload" {
  api_id                 = aws_apigatewayv2_api.upload.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.upload_backend.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "upload" {
  api_id             = aws_apigatewayv2_api.upload.id
  route_key          = "POST /upload"
  target             = "integrations/${aws_apigatewayv2_integration.upload.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.upload.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.upload_backend.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.upload.execution_arn}/*/*"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.upload.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-authorizer"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.frontend.id]
    issuer   = "https://cognito-idp.ap-southeast-2.amazonaws.com/${aws_cognito_user_pool.operators.id}"
  }
}