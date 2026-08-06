import sys
import os
import pytest

# Add src/function to Python path so we can import scan_text_for_pii
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src/function")))

from main import scan_text_for_pii

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
    sample_text = "Payment card 4532-1234-5678-9012 charged $50."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "RESTRICTED"
    assert "CREDIT_CARD" in result["pii_detected"]

def test_clean_public_document():
    sample_text = "Public City Council Meeting Agenda for March 2026."
    result = scan_text_for_pii(sample_text)
    assert result["classification"] == "PUBLIC"
    assert len(result["pii_detected"]) == 0