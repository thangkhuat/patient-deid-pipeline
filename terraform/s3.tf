# s3.tf
resource "aws_s3_bucket" "input_notes" {
  bucket = "patient-deid-input-notes"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "input_notes" {
  bucket = aws_s3_bucket.input_notes.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.input_notes.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "input_notes" {
  bucket = aws_s3_bucket.input_notes.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}