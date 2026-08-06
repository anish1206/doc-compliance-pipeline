terraform {
  required_providers {
    minio = {
      source  = "aminueza/minio"
      version = "1.15.2"
    }
  }
}

# Configure the MinIO Provider (Points to our local Docker container)
provider "minio" {
  minio_server   = "localhost:9000"
  minio_user     = "minioadmin"
  minio_password = "minioadminpassword"
  minio_ssl      = false
}

# 1. Provision the Inbox Bucket for raw user uploads
resource "minio_s3_bucket" "inbox_bucket" {
  bucket = "inbox-bucket"
  acl    = "private"
}

# 2. Provision the Archive Bucket for long-term encrypted storage
resource "minio_s3_bucket" "archive_bucket" {
  bucket = "archive-bucket"
  acl    = "private"
}

# Output the bucket names after provisioning
output "inbox_bucket_name" {
  value = minio_s3_bucket.inbox_bucket.bucket
}

output "archive_bucket_name" {
  value = minio_s3_bucket.archive_bucket.bucket
}

# IAM Policy 1: Restricts Web App to PutObject ONLY on inbox-bucket
resource "minio_iam_policy" "uploader_policy" {
  name   = "uploader-least-privilege"
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": ["arn:aws:s3:::inbox-bucket/*"]
    }
  ]
}
EOF
}

# IAM Policy 2: Restricts Scanner to Inbox Read/Delete & Archive Write
resource "minio_iam_policy" "archiver_policy" {
  name   = "archiver-least-privilege"
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::inbox-bucket/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": ["arn:aws:s3:::archive-bucket/*"]
    }
  ]
}
EOF
}