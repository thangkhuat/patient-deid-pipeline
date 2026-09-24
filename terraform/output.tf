output "upload_api_url" {
  description = "Invoke URL for the upload endpoint"
  value       = "${aws_apigatewayv2_api.upload.api_endpoint}/upload"
}