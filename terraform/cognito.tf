# cognito.tf
resource "aws_cognito_user_pool" "operators" {
  name = "patient-deid-operators"

  # Confirmed from AWS's own security guidance: self-signup would let
  # anyone create an account, no more restrictive than no auth at all.
  # Admin-created accounts only, matching the actual accountable-identity
  # model this project's Reviewer/Operator roles were already designed
  # around.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  mfa_configuration = "ON"

  software_token_mfa_configuration {
    enabled = true
  }
}

resource "aws_cognito_user_pool_domain" "operators" {
  domain       = "patient-deid-auth"
  user_pool_id = aws_cognito_user_pool.operators.id
}

resource "aws_cognito_user_pool_client" "frontend" {
  name         = "patient-deid-frontend"
  user_pool_id = aws_cognito_user_pool.operators.id

  # No client secret -- this runs entirely in browser JavaScript, and a
  # secret embedded there would be exactly the same exposure problem
  # already ruled out for the shared-secret approach.
  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"] # Authorization Code Grant
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = ["https://d2tno7uvqes2o4.cloudfront.net"]
  logout_urls   = ["https://d2tno7uvqes2o4.cloudfront.net"]

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
}

output "cognito_login_url" {
  value = "https://${aws_cognito_user_pool_domain.operators.domain}.auth.ap-southeast-2.amazoncognito.com/login?client_id=${aws_cognito_user_pool_client.frontend.id}&response_type=code&scope=openid+email&redirect_uri=https://d2tno7uvqes2o4.cloudfront.net"
}