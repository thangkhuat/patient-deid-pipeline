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

# Versioning: recovery from an accidental overwrite or delete. Once
# enabled it can never be fully disabled again, only suspended, and every
# overwrite and delete (including the delete markers `aws s3 sync --delete`
# leaves on the frontend bucket) keeps the old version as a billed object.
# Negligible at this project's scale, but a semi-permanent tradeoff, not a
# free change. On input_notes and review_artifacts, a deleted object's content
# persists as a noncurrent version for 30 days (see the lifecycle rules below).
resource "aws_s3_bucket_versioning" "input_notes" {
  bucket = aws_s3_bucket.input_notes.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "redacted_output" {
  bucket = aws_s3_bucket.redacted_output.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "review_artifacts" {
  bucket = aws_s3_bucket.review_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Deny any access over a non-TLS connection, whatever IAM otherwise allows.
resource "aws_s3_bucket_policy" "input_notes" {
  bucket = aws_s3_bucket.input_notes.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.input_notes.arn,
          "${aws_s3_bucket.input_notes.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_policy" "redacted_output" {
  bucket = aws_s3_bucket.redacted_output.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.redacted_output.arn,
          "${aws_s3_bucket.redacted_output.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_policy" "review_artifacts" {
  bucket = aws_s3_bucket.review_artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.review_artifacts.arn,
          "${aws_s3_bucket.review_artifacts.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# Expires noncurrent versions after 30 days, so a deleted note's PHI doesn't
# linger indefinitely as an old version. The window is recorded in
# decision-log.md.
resource "aws_s3_bucket_lifecycle_configuration" "input_notes" {
  bucket = aws_s3_bucket.input_notes.id

  # Noncurrent-version rules need versioning to exist first; nothing else
  # tells Terraform to create them in that order.
  depends_on = [aws_s3_bucket_versioning.input_notes]

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # Kept as a separate rule from noncurrent expiry. Behaviour is the same
  # either way; the split avoids any provider drift on combined rules.
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "review_artifacts" {
  bucket = aws_s3_bucket.review_artifacts.id

  depends_on = [aws_s3_bucket_versioning.review_artifacts]

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # Separate rule for the same reason as input_notes above.
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
}
