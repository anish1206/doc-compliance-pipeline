import io
import re
import os
import json
import time
import threading
from datetime import datetime
from pypdf import PdfReader
import fitz  # PyMuPDF for PDF text coordinate detection & redaction
import redis
import functions_framework
from minio import Minio
from cryptography.fernet import Fernet
import firebase_admin
from firebase_admin import credentials, firestore

# ------------------------------------------------------------------
# 1. REGEX PATTERNS & VALIDATORS FOR PII & COMPLIANCE DETECTION
# ------------------------------------------------------------------

# Comprehensive PII & Enterprise Compliance Regex Patterns
PII_PATTERNS = {
    # ------------------ GLOBAL FINANCIAL & IDENTIFIERS ------------------
    "CREDIT_CARD": re.compile(r'\b(?:\d[ -]*?){13,16}\b'),
    "US_SSN": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),

    # ------------------ INDIA SPECIFIC PII ------------------
    # Aadhaar Number (12 digits, flexibly handles spaces or hyphens; lookbehind/lookahead prevent matching longer runs)
    "IN_AADHAAR": re.compile(r'(?<!\d)(?<!\d\s)(?<!\d-)(?<!\d/)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\s*[-/]?\s*\d)\b'),

    # PAN Card (10 alphanumeric: 5 alphabets + 4 numbers + 1 alphabet)
    "IN_PAN": re.compile(r'\b[A-Za-z]{3}[ABCFGHLJPTabcfghljpt][A-Za-z]\d{4}[A-Za-z]\b'),

    # Indian Mobile Numbers (+91 or 0 prefix optional, starting with 6-9; lookbehind/lookahead prevent matching longer runs)
    "IN_PHONE": re.compile(r'(?<!\d)(?<!\d-)(?<!\d\s)(?:(?:\+|00)91[\s-]?)?[6-9]\d{9}(?!\s*[-/]?\s*\d)\b'),

    # UPI ID / Virtual Payment Address (VPA)
    "IN_UPI_ID": re.compile(
        r'\b[a-zA-Z0-9.\-_]+@(okaxis|okhdfcbank|okicici|oksbi|paytm|ybl|apl|ibl|axl|postbank|upi|gpay|phonepe)\b', 
        re.IGNORECASE
    ),

    # Indian Passport (1 letter followed by 7 digits)
    "IN_PASSPORT": re.compile(r'\b[A-PR-WYa-pr-wy]\d{7}\b'),

    # Voter ID / EPIC Number (Strictly 3 uppercase letters followed by 7 digits)
    "IN_VOTER_ID": re.compile(r'\b[A-Z]{3}\d{7}\b'),

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

# Common English words and system/business identifiers that cause false positives for IN_VOTER_ID
VOTER_ID_EXCLUDED_PREFIXES = {
    # Common 3-letter English words
    "THE", "AND", "FOR", "NOT", "CAN", "ALL", "ANY", "ONE", "TWO", "NEW",
    "OLD", "NOW", "YES", "OUT", "OFF", "END", "TOP", "BOT", "MID", "MAX",
    "MIN", "SUM", "AVG", "CNT", "ERR", "WAR", "INF", "MSG", "CAT", "DOG",
    "CAR", "BUS", "VAN", "BOX", "BAG", "DAY", "MON", "TUE", "WED", "THU",
    "FRI", "SAT", "SUN", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL",
    "AUG", "SEP", "OCT", "NOV", "DEC", "GET", "PUT", "SET", "LET", "SEE",
    # System, technical and business identifiers
    "REF", "DOC", "INV", "EMP", "ORD", "APP", "SYS", "LOG", "DEV", "BUG",
    "TXT", "NUM", "UID", "PID", "JOB", "USR", "SEC", "KEY", "VAL", "RUN",
    "NET", "API", "URL", "PKG", "VER", "SUB", "ADD", "DEL", "TAG", "TAB",
    "ROW", "COL", "REQ", "RES", "ACK", "TAX", "PDF", "CSV", "ZIP", "SQL",
    "DAT", "SRC", "DST", "EXT", "DIR", "BAT", "CMD", "EXE", "DLL", "ISO",
    "BIN", "HEX", "OCT", "DEC", "INT", "FLT", "STR", "ARR", "OBJ", "MAP",
    "FUN", "VAR", "MOD", "PTR", "NIL", "TCP", "UDP", "DNS", "FTP", "SSH",
    "SSL", "TLS"
}


def luhn_checksum(card_number: str) -> bool:
    """
    Validates a credit card number using the Luhn checksum algorithm (Mod 10).
    Filters out non-credit card 13-16 digit sequences like phone numbers or order IDs.
    """
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reversed_digits = digits[::-1]
    for idx, digit in enumerate(reversed_digits):
        if idx % 2 == 1:
            doubled = digit * 2
            checksum += (doubled - 9) if doubled > 9 else doubled
        else:
            checksum += digit
    return checksum % 10 == 0


def is_valid_voter_id(candidate: str) -> bool:
    """
    Validates Indian Voter ID (EPIC): 3 uppercase letters followed by 7 digits.
    Filters out ordinary lowercase words and common business/system ID prefixes.
    """
    if len(candidate) != 10:
        return False
    prefix = candidate[:3].upper()
    if prefix in VOTER_ID_EXCLUDED_PREFIXES:
        return False
    return candidate[:3].isupper() and candidate[3:].isdigit()


def extract_pii_matches(text: str) -> list[dict]:
    """
    Extracts all candidate PII matches from text with span positions,
    validates candidates (Luhn for Credit Cards, prefix filter for Voter ID),
    and deduplicates overlapping matches with priority:
    CREDIT_CARD > IN_AADHAAR > IN_PHONE > others.
    """
    raw_matches = []

    for pii_type, pattern in PII_PATTERNS.items():
        for match in pattern.finditer(text):
            val = match.group(0)
            start, end = match.start(), match.end()

            # Rule validations
            if pii_type == "CREDIT_CARD":
                if not luhn_checksum(val):
                    continue
            elif pii_type == "IN_VOTER_ID":
                if not is_valid_voter_id(val):
                    continue

            raw_matches.append({
                "type": pii_type,
                "text": val,
                "start": start,
                "end": end
            })

    # Priority rank: lower number = higher priority
    priority_rank = {
        "CREDIT_CARD": 1,
        "IN_AADHAAR": 2,
        "IN_PHONE": 3,
        "IN_PAN": 4,
        "IN_PASSPORT": 5,
        "IN_VOTER_ID": 6,
        "US_SSN": 7,
        "EMAIL": 8,
        "IN_UPI_ID": 9,
        "IN_DRIVING_LICENSE": 10,
        "IN_IFSC": 11,
        "AWS_ACCESS_KEY": 12,
        "PRIVATE_KEY": 13,
        "CONFIDENTIAL_KEYWORD": 14
    }

    # Sort matches: higher priority first, then longer span first
    sorted_matches = sorted(
        raw_matches,
        key=lambda m: (priority_rank.get(m["type"], 99), -(m["end"] - m["start"]), m["start"])
    )

    accepted_matches = []
    for m in sorted_matches:
        # Check if this candidate overlaps with any already accepted match
        overlaps = False
        for a in accepted_matches:
            if max(m["start"], a["start"]) < min(m["end"], a["end"]):
                overlaps = True
                break
        if not overlaps:
            accepted_matches.append(m)

    accepted_matches.sort(key=lambda m: m["start"])
    return accepted_matches


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
    Scans plain text against Regex rules, performs checksum/context validation,
    deduplicates overlapping matches, and returns classification + detected PII.
    """
    matches = extract_pii_matches(text)

    # Maintain stable list of unique detected PII types
    detected_pii = []
    for m in matches:
        if m["type"] not in detected_pii:
            detected_pii.append(m["type"])

    classification = "RESTRICTED" if detected_pii else "PUBLIC"

    return {
        "classification": classification,
        "pii_detected": detected_pii,
        "matches": [m["text"] for m in matches]
    }


def redact_pdf(raw_pdf_bytes: bytes, terms_to_redact: list[str]) -> bytes:
    """
    Burns solid black redaction boxes over detected PII coordinates using PyMuPDF (fitz),
    permanently erasing underlying text streams for the public viewing tier.
    """
    doc = fitz.open(stream=raw_pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            for term in terms_to_redact:
                if not term or not term.strip():
                    continue
                # Search for bounding rects of the sensitive term
                rects = page.search_for(term)
                for rect in rects:
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                
                # Also search for space-collapsed digit runs (e.g. 234567890123)
                digits_only = "".join(c for c in term if c.isdigit())
                if len(digits_only) >= 10 and digits_only != term:
                    for rect in page.search_for(digits_only):
                        page.add_redact_annot(rect, fill=(0, 0, 0))

            page.apply_redactions()
        return doc.tobytes(deflate=True)
    finally:
        doc.close()


# ------------------------------------------------------------------
# 2. CLIENT INITIALIZATIONS (MinIO, Redis & Firebase Firestore)
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

# Redis Configuration (Asynchronous task queue)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_QUEUE = os.getenv("REDIS_QUEUE", "scan_queue")

# Encryption Key (Fernet AES-128/256 for private vault archive)
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


def get_redis_client():
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"[Redis] Warning: Unable to connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
        return None


# ------------------------------------------------------------------
# 3. CORE PROCESSING PIPELINE (Multi-Tier Storage & Redaction)
# ------------------------------------------------------------------

def process_file(filename: str) -> dict:
    """
    Executes the complete document compliance workflow:
    1. Downloads raw PDF from inbox-bucket.
    2. Extracts text & executes regex + Luhn/context PII scan.
    3. AES-256 encrypts original file to private vault (archive-bucket).
    4. PyMuPDF redacts sensitive coordinates and uploads to public-bucket.
    5. Ingestion purge removes raw unencrypted file from inbox-bucket.
    6. Writes metadata record to Cloud Firestore.
    """
    print(f"[Pipeline] Processing compliance scan for: {filename}")

    # Ensure required MinIO buckets exist
    for bucket in ["inbox-bucket", "archive-bucket", "public-bucket"]:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)

    # Step 1: Download raw PDF from MinIO inbox-bucket
    response = minio_client.get_object("inbox-bucket", filename)
    raw_pdf_bytes = response.read()
    response.close()
    response.release_conn()

    # Step 2: Extract Text & Scan for PII
    extracted_text = extract_text_from_bytes(raw_pdf_bytes)
    scan_results = scan_text_for_pii(extracted_text)

    # Step 3a: Private Vault Tier — Encrypt original PDF with AES-256 and store in archive-bucket
    encrypted_bytes = cipher_suite.encrypt(raw_pdf_bytes)
    encrypted_stream = io.BytesIO(encrypted_bytes)
    minio_client.put_object(
        "archive-bucket",
        f"archived_{filename}",
        encrypted_stream,
        length=len(encrypted_bytes),
        content_type="application/octet-stream"
    )

    # Step 3b: Public Viewing Tier — PyMuPDF Redaction to public-bucket
    if scan_results["pii_detected"]:
        redacted_bytes = redact_pdf(raw_pdf_bytes, scan_results["matches"])
    else:
        # Public clean document requires no redaction boxes
        redacted_bytes = raw_pdf_bytes

    redacted_stream = io.BytesIO(redacted_bytes)
    redacted_filename = f"redacted_{filename}"
    minio_client.put_object(
        "public-bucket",
        redacted_filename,
        redacted_stream,
        length=len(redacted_bytes),
        content_type="application/pdf"
    )

    # Step 3c: Ingestion Purge — Delete raw file from inbox-bucket
    minio_client.remove_object("inbox-bucket", filename)

    # Step 4: Write Metadata to Google Cloud Firestore
    metadata = {
        "filename": filename,
        "classification": scan_results["classification"],
        "pii_detected": scan_results["pii_detected"],
        "archive_path": f"archive-bucket/archived_{filename}",
        "public_path": f"public-bucket/{redacted_filename}",
        "redacted_filename": redacted_filename,
        "file_size_bytes": len(raw_pdf_bytes),
        "processed_at": datetime.utcnow().isoformat()
    }

    db = get_firestore_db()
    if db:
        db.collection("documents").add(metadata)
        print(f"[Firestore] Document metadata written successfully for {filename}")

    return metadata


# ------------------------------------------------------------------
# 4. REDIS ASYNC WORKER LOOP & SERVERLESS HTTP HANDLER
# ------------------------------------------------------------------

def run_worker_loop():
    """
    Background worker loop continuously polling the Redis task queue
    via blpop for asynchronous processing jobs.
    """
    print(f"[Worker] Starting Redis async worker listening on '{REDIS_QUEUE}'...")
    while True:
        try:
            r = get_redis_client()
            if not r:
                time.sleep(3)
                continue

            # Blocking pop on Redis queue with 2-second timeout
            item = r.blpop(REDIS_QUEUE, timeout=2)
            if item:
                _, job_data = item
                try:
                    payload = json.loads(job_data)
                    filename = payload.get("filename")
                    if filename:
                        print(f"[Worker] Dequeued job for {filename}")
                        process_file(filename)
                except Exception as je:
                    print(f"[Worker] Failed to process job payload {job_data}: {je}")
        except Exception as e:
            print(f"[Worker] Error in worker loop: {e}")
            time.sleep(2)


# Start background Redis worker thread on module load
worker_thread = threading.Thread(target=run_worker_loop, daemon=True)
worker_thread.start()


@functions_framework.http
def scan_document(request):
    """
    HTTP Serverless Function Entrypoint (supports direct HTTP triggers as well).
    Expects JSON: { "filename": "sample.pdf" }
    """
    request_json = request.get_json(silent=True)
    if not request_json or "filename" not in request_json:
        return json.dumps({"error": "Missing 'filename' in request body"}), 400, {"Content-Type": "application/json"}

    filename = request_json["filename"]
    try:
        metadata = process_file(filename)
        return json.dumps({
            "status": "SUCCESS",
            "filename": filename,
            "result": metadata
        }), 200, {"Content-Type": "application/json"}
    except Exception as e:
        print(f"[Error] Scanning failed for {filename}: {e}")
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    print("[Worker] Running Scanner Worker directly in foreground...")
    run_worker_loop()