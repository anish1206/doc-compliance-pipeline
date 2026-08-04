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