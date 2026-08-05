import os
import io
import requests
from flask import Flask, render_template, request, jsonify
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

# MinIO Client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

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
    Receives PDF from Frontend, saves to MinIO inbox-bucket,
    and triggers the Serverless Scanner API.
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
        # Ensure bucket exists first
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

        # Step 2: Trigger Serverless Scanner API
        response = requests.post(
            SCANNER_API_URL,
            json={"filename": filename},
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 200:
            scan_result = response.json()
            return jsonify({
                "message": "File processed successfully",
                "data": scan_result.get("result")
            }), 200
        else:
            return jsonify({"error": f"Scanner failed: {response.text}"}), 500

    except Exception as e:
        print(f"[Error] Upload pipeline failed: {e}")
        return jsonify({"error": str(e)}), 500


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