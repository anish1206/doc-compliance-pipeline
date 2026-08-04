### MinIO

MinIO is an open-source, S3-compatible object storage system, meaning it stores files as objects and exposes an API similar to Amazon S3. It is commonly used for backups, media, logs, and AI/data workloads, especially when you want S3-like storage on your own infrastructure.

---

Running project

| Starting                                | Closing                                                                                                                                                                |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| rootdocker compose up -d               | root*(Note: If you want to keep your MinIO uploaded files intact while stopping the container, you can run docker compose stop instead of down).*docker compose down |
| terraform/terraform apply -auto-approv | terraform/terraform destroy                                                                                                                                           |

---
