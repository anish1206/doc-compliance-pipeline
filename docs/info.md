Running project

| Starting                                   | Closing                                                                                                                                                                 |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `root docker compose up -d `               | `root (Note: If you want to keep your MinIO uploaded files intact while stopping the container, you can run docker compose stop instead of down). docker compose down ` |
| `terraform/ terraform apply -auto-approv ` | `terraform/ terraform destroy `                                                                                                                                         |

---

### MinIO

MinIO is an open-source, S3-compatible object storage system, meaning it stores files as objects and exposes an API similar to Amazon S3. It is commonly used for backups, media, logs, and AI/data workloads, especially when you want S3-like storage on your own infrastructure.

---

### What is functions-framework?

In production Google Cloud, when a file hits a bucket, GCP automatically executes your Python code inside a managed container.

How does Google do this? Google built an open-source tool called **functions-framework**.

- It takes a normal Python function (e.g., def scan_document(request):) and turns it into a web server listener.
- This allows us to run and test **the exact same Cloud Function code locally on your laptop** inside Docker, without needing a cloud server

---

### Our Flask backend has 3 core routes:

- **GET / (Serves the UI):**
  - Renders index.html from the templates/ folder.
- **POST /api/upload (Handles File Upload & Scanner Trigger):**
  - Receives the uploaded PDF file from JavaScript (FormData).
  - Saves the file into memory and uploads it directly to MinIO inbox-bucket.
  - Sends an HTTP POST call (requests.post) to our Serverless Scanner at [http://localhost:8080](http://localhost:8080) with {"filename": filename}.
  - Returns the compliance result JSON back to the JavaScript frontend.
- **GET /api/documents (Fetches Live Compliance History):**
  - Queries Cloud Firestore documents collection.
  - Retrieves all processed documents ordered by timestamp.
  - Returns a JSON array so JavaScript can render the live status table.
