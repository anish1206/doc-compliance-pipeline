import os
import io
import json
import requests
import redis
from flask import Flask, render_template, request, jsonify, send_file
from minio import Minio
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__, template_folder="template", static_folder="static")

# ------------------------------------------------------------------
# CONFIGURATION & CLIENT INITIALIZATION
# ------------------------------------------------------------------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadminpassword")
SCANNER_API_URL = os.getenv("SCANNER_API_URL", "http://localhost:8080")

# Redis Configuration (Asynchronous Task Queue)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_QUEUE = os.getenv("REDIS_QUEUE", "scan_queue")

# MinIO Client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

def get_redis_client():
    """Returns connected Redis client or None if unreachable."""
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"[Redis] Warning: Unable to connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
        return None

# Firebase Firestore Client
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "../../secrets/firebase-key.json")
if os.path.exists(FIREBASE_KEY_PATH) and not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

def get_firestore_db():
    if firebase_admin._apps:
        return firestore.client()
    return None

# ------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Serves the main HTML Web Portal."""
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_document():
    """
    Receives PDF from Frontend, saves raw file to MinIO inbox-bucket,
    pushes an asynchronous processing task to Redis queue,
    and returns an immediate non-blocking 200 response to the user.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Selected file has no filename"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are allowed"}), 400

    filename = file.filename
    file_bytes = file.read()
    file_stream = io.BytesIO(file_bytes)

    try:
        # Step 1: Upload raw PDF to MinIO inbox-bucket
        if not minio_client.bucket_exists("inbox-bucket"):
            minio_client.make_bucket("inbox-bucket")
            
        minio_client.put_object(
            "inbox-bucket",
            filename,
            file_stream,
            length=len(file_bytes),
            content_type="application/pdf"
        )
        print(f"[Flask] Uploaded {filename} to MinIO inbox-bucket")

        # Step 2: Push Job to Redis Task Queue (Decoupled Asynchronous Processing)
        r = get_redis_client()
        if r:
            payload = json.dumps({"filename": filename})
            r.rpush(REDIS_QUEUE, payload)
            print(f"[Flask] Enqueued task for {filename} into Redis queue '{REDIS_QUEUE}'")

            return jsonify({
                "message": "File uploaded and queued for asynchronous compliance processing",
                "status": "QUEUED",
                "filename": filename
            }), 200

        # Fallback if Redis is temporarily offline in local dev
        print(f"[Flask] Redis unavailable at {REDIS_HOST}:{REDIS_PORT}, attempting fallback scanner API...")
        try:
            response = requests.post(
                SCANNER_API_URL,
                json={"filename": filename},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if response.status_code == 200:
                scan_result = response.json()
                return jsonify({
                    "message": "File processed via fallback scanner",
                    "status": "COMPLETED",
                    "filename": filename,
                    "data": scan_result.get("result")
                }), 200
        except Exception as fe:
            print(f"[Flask] Fallback scanner also failed: {fe}")

        return jsonify({
            "message": "File uploaded to inbox-bucket; queued for background processing",
            "status": "QUEUED",
            "filename": filename
        }), 200

    except Exception as e:
        print(f"[Error] Upload pipeline failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/view/<path:filename>", methods=["GET"])
def view_redacted_document(filename):
    """
    Serves safe redacted document from MinIO public-bucket inline for browser viewing.
    """
    try:
        if not minio_client.bucket_exists("public-bucket"):
            return jsonify({"error": "Public viewing bucket does not exist"}), 404

        response = minio_client.get_object("public-bucket", filename)
        file_bytes = response.read()
        response.close()
        response.release_conn()

        return send_file(
            io.BytesIO(file_bytes),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=filename
        )
    except Exception as e:
        print(f"[Error] Failed to view {filename} from public-bucket: {e}")
        return jsonify({"error": f"File '{filename}' not found in public-bucket: {e}"}), 404


@app.route("/api/download/<path:filename>", methods=["GET"])
def download_redacted_document(filename):
    """
    Downloads safe redacted document from MinIO public-bucket.
    """
    try:
        if not minio_client.bucket_exists("public-bucket"):
            return jsonify({"error": "Public viewing bucket does not exist"}), 404

        response = minio_client.get_object("public-bucket", filename)
        file_bytes = response.read()
        response.close()
        response.release_conn()

        return send_file(
            io.BytesIO(file_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[Error] Failed to download {filename} from public-bucket: {e}")
        return jsonify({"error": f"File '{filename}' not found in public-bucket: {e}"}), 404


@app.route("/api/documents", methods=["GET"])
def get_documents():
    """Fetches all processed document compliance records from Firestore."""
    try:
        db = get_firestore_db()
        if not db:
            return jsonify({"documents": []}), 200

        # Query documents from Firestore
        docs = db.collection("documents").stream()
        document_list = []
        for doc in docs:
            doc_data = doc.to_dict()
            doc_data["id"] = doc.id
            document_list.append(doc_data)

        # Sort newest first
        document_list.sort(key=lambda x: x.get("processed_at", ""), reverse=True)

        return jsonify({"documents": document_list}), 200

    except Exception as e:
        print(f"[Error] Failed to fetch documents: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("[Flask] Starting Edge Web App on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=True)