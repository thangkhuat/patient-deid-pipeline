resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket = "patient-deid-cloudtrail-logs"
}

resource "aws_s3_bucket_public_access_block" "cloudtrail_logs" {
  bucket                  = aws_s3_bucket.cloudtrail_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

locals {
  cloudtrail_arn = "arn:aws:cloudtrail:ap-southeast-2:${data.aws_caller_identity.current.account_id}:trail/patient-deid-review-artifacts-access"
}

resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail_logs.arn
        Condition = { StringEquals = { "aws:SourceArn" = local.cloudtrail_arn } }
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = local.cloudtrail_arn
          }
        }
      },
      # Same TLS-only deny as the other buckets. It lives in this policy
      # rather than a separate aws_s3_bucket_policy: a bucket has exactly one
      # policy, so a second resource would overwrite CloudTrail's grants above.
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.cloudtrail_logs.arn,
          "${aws_s3_bucket.cloudtrail_logs.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# Versioning and lifecycle match the other buckets in s3.tf.
resource "aws_s3_bucket_versioning" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  depends_on = [aws_s3_bucket_versioning.cloudtrail_logs]

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # Separate rule, matching input_notes and review_artifacts in s3.tf:
  # combining this with noncurrent expiry in one rule is reported to drift
  # in the AWS provider (the stored config doesn't persist as written).
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
}

resource "aws_cloudtrail" "review_artifacts_access" {
  name                          = "patient-deid-review-artifacts-access"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  include_global_service_events = false
  is_multi_region_trail         = false

  # Scoped to exactly one question: who read a specific object in
  # review-artifacts. Not account-wide, not even all actions on this
  # one bucket -- just GetObject, matching the actual stated need.
  advanced_event_selector {
    name = "GetObject reads on review-artifacts"

    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }
    field_selector {
      field       = "resources.ARN"
      starts_with = ["${aws_s3_bucket.review_artifacts.arn}/"]
    }
    field_selector {
      field  = "eventName"
      equals = ["GetObject"]
    }
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail_logs]
}