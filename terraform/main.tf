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

# 3. Provision the Public Bucket for safe redacted viewing tier
resource "minio_s3_bucket" "public_bucket" {
  bucket = "public-bucket"
  acl    = "public-read"
}

# Output the bucket names after provisioning
output "inbox_bucket_name" {
  value = minio_s3_bucket.inbox_bucket.bucket
}

output "archive_bucket_name" {
  value = minio_s3_bucket.archive_bucket.bucket
}

output "public_bucket_name" {
  value = minio_s3_bucket.public_bucket.bucket
}

# IAM Policy 1: Restricts Web App to PutObject on inbox-bucket and GetObject on public-bucket
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
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::public-bucket/*"]
    }
  ]
}
EOF
}

# IAM Policy 2: Restricts Scanner to Inbox Read/Delete, Archive Write & Public Redacted Write
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
      "Resource": [
        "arn:aws:s3:::archive-bucket/*",
        "arn:aws:s3:::public-bucket/*"
      ]
    }
  ]
}
EOF
}