variable "encryption_key" {
  description = "Fernet key for review_queue encryption -- interim, never committed"
  type        = string
  sensitive   = true
}

variable "operator_user_name" {
  description = "IAM user allowed to decrypt redacted-output (operator/testing access)"
  type        = string
}