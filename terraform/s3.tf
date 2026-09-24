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

resource "aws_s3_bucket" "redacted_output" {
  bucket = "patient-deid-redacted-output"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "redacted_output" {
  bucket = aws_s3_bucket.redacted_output.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.redacted_output.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "redacted_output" {
  bucket                  = aws_s3_bucket.redacted_output.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "review_artifacts" {
  bucket = "patient-deid-review-artifacts"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "review_artifacts" {
  bucket = aws_s3_bucket.review_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.review_artifacts.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "review_artifacts" {
  bucket                  = aws_s3_bucket.review_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}