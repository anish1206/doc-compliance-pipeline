import sys
import os
import io
import pytest
import fitz

# Add src/function to Python path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/function")))

from main import scan_text_for_pii, luhn_checksum, is_valid_voter_id, redact_pdf


def test_aadhaar_detection():
    sample_text = "Client Aadhaar number is 2345 6789 0123 for verification."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "IN_AADHAAR" in result["pii_detected"]


def test_pan_detection():
    sample_text = "Taxpayer PAN details: ABCPE1234F."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "IN_PAN" in result["pii_detected"]


def test_credit_card_detection():
    # 4532-1234-5678-9014 is a valid Luhn test card number
    sample_text = "Payment card 4532-1234-5678-9014 charged $50."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "CREDIT_CARD" in result["pii_detected"]


def test_credit_card_luhn_rejection():
    # 16-digit order ID that fails Luhn checksum must NOT be flagged as credit card
    sample_text = "Order shipment reference 1234-5678-9012-3456 delivered."
    result = scan_text_for_pii(sample_text)
    assert "CREDIT_CARD" not in result["pii_detected"]
    assert result["classification"] == "PUBLIC"


def test_voter_id_valid_detection():
    sample_text = "Voter registered with EPIC ID WBH1234567 in district 4."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "IN_VOTER_ID" in result["pii_detected"]


def test_voter_id_false_positives_filtered():
    # Lowercase ordinary words followed by 7 digits
    words_sample = "Processed records the1234567 and doc1234567 successfully."
    result_words = scan_text_for_pii(words_sample)
    assert "IN_VOTER_ID" not in result_words["pii_detected"]
    assert result_words["classification"] == "PUBLIC"

    # Common business / system IDs
    ids_sample = "System ticket REF1234567, Employee EMP1234567, Invoice INV1234567."
    result_ids = scan_text_for_pii(ids_sample)
    assert "IN_VOTER_ID" not in result_ids["pii_detected"]
    assert result_ids["classification"] == "PUBLIC"


def test_deduplicate_credit_card_overlap():
    # 16-digit credit card should NOT trigger sub-span IN_AADHAAR or IN_PHONE
    sample_text = "Card number 4532 1234 5678 9014 verified by issuer."
    result = scan_text_for_pii(sample_text)
    assert "CREDIT_CARD" in result["pii_detected"]
    assert "IN_AADHAAR" not in result["pii_detected"]
    assert "IN_PHONE" not in result["pii_detected"]


def test_deduplicate_aadhaar_phone_overlap():
    # Aadhaar number whose first 10 digits look like a phone number starting with 9
    sample_text = "Resident Aadhaar: 9876 5432 1012."
    result = scan_text_for_pii(sample_text)
    assert "IN_AADHAAR" in result["pii_detected"]
    assert "IN_PHONE" not in result["pii_detected"]


def test_standalone_phone_detection():
    sample_text = "Contact customer care at +91 9876543210 for assistance."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "IN_PHONE" in result["pii_detected"]


def test_clean_public_document():
    sample_text = "Public City Council Meeting Agenda for March 2026."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "PUBLIC"
    assert len(result["pii_detected"]) == 0


def test_pymupdf_pdf_redaction():
    # Create an in-memory PDF with sensitive text
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Taxpayer PAN is ABCPE1234F recorded.")
    raw_pdf_bytes = doc.tobytes()
    doc.close()

    # Apply PyMuPDF redaction
    redacted_bytes = redact_pdf(raw_pdf_bytes, ["ABCPE1234F"])
    assert len(redacted_bytes) > 0

    # Verify that the sensitive PAN string is completely stripped from the text stream
    redacted_doc = fitz.open(stream=redacted_bytes, filetype="pdf")
    redacted_text = redacted_doc[0].get_text()
    redacted_doc.close()

    assert "ABCPE1234F" not in redacted_text