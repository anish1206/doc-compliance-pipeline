import io
import re
import os
import json
from pypdf import PdfReader

import functions_framework
from minio import Minio
from cryptography.fernet import Fernet
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# ------------------------------------------------------------------
# 1. REGEX PATTERNS FOR PII & COMPLIANCE DETECTION
# ------------------------------------------------------------------
import re
# ------------------------------------------------------------------
# COMPREHENSIVE PII & ENTERPRISE COMPLIANCE REGEX PATTERNS
# ------------------------------------------------------------------
PII_PATTERNS = {
    # ------------------ GLOBAL FINANCIAL & IDENTIFIERS ------------------
    "CREDIT_CARD": re.compile(r'\b(?:\d[ -]*?){13,16}\b'),
    "US_SSN": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),

    # ------------------ INDIA SPECIFIC PII ------------------
    # Aadhaar Number (12 digits, flexibly handles spaces, hyphens, or newlines)
    "IN_AADHAAR": re.compile(r'\b[2-9]\d{3}[\s-]*?\d{4}[\s-]*?\d{4}\b'),

    # PAN Card (10 alphanumeric: 5 alphabets + 4 numbers + 1 alphabet)
    "IN_PAN": re.compile(r'\b[A-Za-z]{3}[ABCFGHLJPTabcfghljpt][A-Za-z]\d{4}[A-Za-z]\b'),

    # Indian Mobile Numbers (+91 or 0 prefix optional, starting with 6-9)
    "IN_PHONE": re.compile(r'\b(?:(?:\+|00)91[\s-]?)?[6-9]\d{9}\b'),

    # UPI ID / Virtual Payment Address (VPA)
    "IN_UPI_ID": re.compile(
        r'\b[a-zA-Z0-9.\-_]+@(okaxis|okhdfcbank|okicici|oksbi|paytm|ybl|apl|ibl|axl|postbank|upi|gpay|phonepe)\b', 
        re.IGNORECASE
    ),

    # Indian Passport (1 letter followed by 7 digits)
    "IN_PASSPORT": re.compile(r'\b[A-PR-WYa-pr-wy]\d{7}\b'),

    # Voter ID / EPIC Number (3 letters followed by 7 digits)
    "IN_VOTER_ID": re.compile(r'\b[A-Za-z]{3}\d{7}\b'),

    # Indian Driving License (State code + RTO code + digits)
    "IN_DRIVING_LICENSE": re.compile(r'\b[A-Za-z]{2}\d{2}[\s-]*?\d{11}\b'),

    # IFSC Code (Bank routing: 4 alphabets + 0 + 6 alphanumeric)
    "IN_IFSC": re.compile(r'\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b'),

    # ------------------ ENTERPRISE SECRETS & KEYS ------------------
    "AWS_ACCESS_KEY": re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    "PRIVATE_KEY": re.compile(r'-----BEGIN (?:RSA|EC|PGP|OPENSSH)? PRIVATE KEY-----'),

    # ------------------ CLASSIFICATION KEYWORDS ------------------
    "CONFIDENTIAL_KEYWORD": re.compile(
        r'\b(CONFIDENTIAL|RESTRICTED|TOP SECRET|PRIVILEGED|STRICTLY PRIVATE|DO NOT DISCLOSE|INTERNAL USE ONLY)\b', 
        re.IGNORECASE
    )
}

def extract_text_from_bytes(file_bytes: bytes) -> str:
    """
    Extracts plain text from raw PDF bytes using pypdf in memory.
    """
    text = ""
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        print(f"[Error] Failed to parse PDF text: {e}")
    return text

def scan_text_for_pii(text: str) -> dict:
    """
    Scans plain text against Regex rules and returns classification + detected PII.
    """
    detected_pii = []
    
    for pii_type, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            detected_pii.append(pii_type)
            
    # Classification Logic
    if detected_pii:
        classification = "RESTRICTED"
    else:
        classification = "PUBLIC"
        
    return {
        "classification": classification,
        "pii_detected": detected_pii
    }


# ------------------------------------------------------------------
# 2. CLIENT INITIALIZATIONS (MinIO & Firebase Firestore)
# ------------------------------------------------------------------

# MinIO Client (Connects to MinIO container)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadminpassword")

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

# Encryption Key (Fernet AES-128/256)
ENCRYPTION_KEY = Fernet.generate_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

# Firebase Cloud Firestore Setup
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "../../secrets/firebase-key.json")
if os.path.exists(FIREBASE_KEY_PATH) and not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

def get_firestore_db():
    if firebase_admin._apps:
        return firestore.client()
    return None

# ------------------------------------------------------------------
# 3. SERVERLESS HTTP ENTRY POINT
# ------------------------------------------------------------------
@functions_framework.http
def scan_document(request):
    """
    HTTP Serverless Function Entrypoint.
    Expects JSON: { "filename": "sample.pdf" }
    """
    request_json = request.get_json(silent=True)
    if not request_json or "filename" not in request_json:
        return json.dumps({"error": "Missing 'filename' in request body"}), 400, {"Content-Type": "application/json"}

    filename = request_json["filename"]
    print(f"[Trigger] Starting compliance scan for file: {filename}")

    try:
        # Step 1: Download PDF from MinIO inbox-bucket
        response = minio_client.get_object("inbox-bucket", filename)
        raw_pdf_bytes = response.read()
        response.close()
        response.release_conn()

        # Step 2: Extract Text & Scan for PII
        extracted_text = extract_text_from_bytes(raw_pdf_bytes)
        scan_results = scan_text_for_pii(extracted_text)

        # Step 3: Encrypt & Move to Archive Bucket
        encrypted_bytes = cipher_suite.encrypt(raw_pdf_bytes)
        encrypted_stream = io.BytesIO(encrypted_bytes)

        minio_client.put_object(
            "archive-bucket",
            f"archived_{filename}",
            encrypted_stream,
            length=len(encrypted_bytes),
            content_type="application/octet-stream"
        )

        # Delete raw file from inbox-bucket (Clean isolation)
        minio_client.remove_object("inbox-bucket", filename)

        # Step 4: Write Metadata to Firebase Cloud Firestore
        metadata = {
            "filename": filename,
            "classification": scan_results["classification"],
            "pii_detected": scan_results["pii_detected"],
            "archive_path": f"archive-bucket/archived_{filename}",
            "file_size_bytes": len(raw_pdf_bytes),
            "processed_at": datetime.utcnow().isoformat()
        }

        db = get_firestore_db()
        if db:
            db.collection("documents").add(metadata)
            print(f"[Firestore] Document metadata written successfully for {filename}")

        return json.dumps({
            "status": "SUCCESS",
            "filename": filename,
            "result": metadata
        }), 200, {"Content-Type": "application/json"}

    except Exception as e:
        print(f"[Error] Scanning failed for {filename}: {e}")
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}