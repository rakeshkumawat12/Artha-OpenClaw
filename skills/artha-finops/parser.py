"""
parser.py — Signal → Structured Event
Converts raw text (WhatsApp/SMS) into a structured financial event.
"""

import re
import json
from typing import Optional

# Keyword sets for classification
INCOME_KEYWORDS = [
    "received", "credited", "payment received", "transferred to you",
    "deposited", "income", "paid by", "amount credited", "inward",
    "credit", "got paid", "received from"
]

EXPENSE_KEYWORDS = [
    "paid", "debited", "payment made", "transferred", "purchased",
    "expense", "spent", "bought", "subscription", "bill", "fees",
    "debit", "paid for", "charged"
]

INVOICE_KEYWORDS = [
    "send invoice", "generate invoice", "need invoice", "invoice required",
    "raise invoice", "bill them", "create invoice"
]

CURRENCY_PATTERNS = [
    r'[₹Rs\.INR\s]*(\d+(?:,\d{3})*(?:\.\d{1,2})?)',   # ₹25,000 or Rs. 25000
    r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:rupees?|rs\.?|inr)',
]

COUNTERPARTY_PATTERNS = [
    r'(?:from|to|by)\s+([A-Z][A-Za-z\s&\.]+?)(?:\s+for|\s+on|\s*$|\s*\.)',
    r'(?:from|to|by)\s+([A-Z][A-Za-z\s]+)',
]

DESCRIPTION_PATTERNS = [
    r'for\s+([A-Za-z\s\-_\/]+?)(?:\s+on|\s+from|\s+to|\s*$|\s*\.)',
    r'(?:payment|expense|income)\s+(?:for|of)\s+([A-Za-z\s\-_\/]+)',
]


def extract_amount(text: str) -> Optional[float]:
    for pattern in CURRENCY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                continue
    # Fallback: any standalone number
    match = re.search(r'\b(\d{3,}(?:\.\d{1,2})?)\b', text)
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def classify_event(text: str) -> str:
    lower = text.lower()
    for kw in INVOICE_KEYWORDS:
        if kw in lower:
            return "invoice_request"
    income_score = sum(1 for kw in INCOME_KEYWORDS if kw in lower)
    expense_score = sum(1 for kw in EXPENSE_KEYWORDS if kw in lower)
    if income_score >= expense_score:
        return "income"
    return "expense"


def extract_counterparty(text: str) -> str:
    for pattern in COUNTERPARTY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip().rstrip(".")
            if len(name) > 1:
                return name.title()
    return "Unknown"


def extract_description(text: str) -> str:
    for pattern in DESCRIPTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().title()
    # Fallback: return cleaned input text
    clean = re.sub(r'[₹₨]', '', text).strip()
    return clean[:80] if clean else "Financial transaction"


def needs_invoice(text: str, event_type: str) -> bool:
    lower = text.lower()
    if event_type == "invoice_request":
        return True
    if event_type == "income":
        invoice_indicators = ["invoice", "bill", "receipt", "gst", "client"]
        return any(ind in lower for ind in invoice_indicators)
    return False


def compute_confidence(text: str, amount: Optional[float], event_type: str) -> float:
    score = 0.5
    if amount is not None:
        score += 0.2
    if event_type in ("income", "expense"):
        score += 0.15
    if extract_counterparty(text) != "Unknown":
        score += 0.1
    if re.search(r'[₹₨]', text):
        score += 0.05
    return round(min(score, 1.0), 2)


def parse(raw_text: str) -> dict:
    """
    Parse raw input text into a structured financial event.

    Returns:
        {
            "event_type": "income | expense | invoice_request",
            "counterparty": str,
            "amount": float | None,
            "description": str,
            "needs_invoice": bool,
            "confidence": float,
            "raw": str
        }
    """
    text = raw_text.strip()
    amount = extract_amount(text)
    event_type = classify_event(text)
    counterparty = extract_counterparty(text)
    description = extract_description(text)
    invoice_needed = needs_invoice(text, event_type)
    confidence = compute_confidence(text, amount, event_type)

    return {
        "event_type": event_type,
        "counterparty": counterparty,
        "amount": amount,
        "description": description,
        "needs_invoice": invoice_needed,
        "confidence": confidence,
        "raw": text,
    }


if __name__ == "__main__":
    samples = [
        "Received ₹25,000 from ABC Corp for website design",
        "Paid ₹4,500 for Figma subscription",
        "Payment of ₹12,000 received from Zeta Solutions for consulting",
        "Debited ₹1,200 for AWS hosting charges",
        "Send invoice to Nexus Media for ₹50,000",
        "Got paid Rs. 8000 by Priya Sharma for logo design",
    ]
    for s in samples:
        result = parse(s)
        print(json.dumps(result, indent=2))
        print("---")
