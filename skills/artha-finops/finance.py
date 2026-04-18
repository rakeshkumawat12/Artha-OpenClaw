"""
finance.py — Financial Engine
Computes GST, normalizes amounts, and generates invoice metadata.
GST rate is looked up dynamically per product/service via gst_lookup.
"""

from datetime import datetime
import json
import os

from gst_lookup import lookup_gst_rate
from db import gst_update, gst_get

DEFAULT_GST_RATE = 0.18  # fallback only


def compute_gst(amount: float, gst_rate: float, gst_included: bool = True) -> dict:
    """
    Decompose amount into base + GST.

    Args:
        amount: Total amount (may or may not include GST)
        gst_included: If True, GST is already baked into amount

    Returns:
        { base_amount, gst_amount, total_amount, gst_rate }
    """
    if gst_included:
        base = round(amount / (1 + gst_rate), 2)
        gst = round(amount - base, 2)
        total = round(amount, 2)
    else:
        base = round(amount, 2)
        gst = round(amount * gst_rate, 2)
        total = round(base + gst, 2)

    return {
        "base_amount": base,
        "gst_amount": gst,
        "total_amount": total,
        "gst_rate": gst_rate,
    }


def generate_invoice_id() -> str:
    """Generate a unique invoice ID: INV-YYYY-XXXX"""
    year = datetime.now().year
    summary = _load_gst_summary()
    seq = summary.get("invoice_count", 0) + 1
    return f"INV-{year}-{seq:04d}"


def normalize_event(parsed_event: dict) -> dict:
    """
    Take a parsed event and return fully normalized financial data.

    Returns:
        {
            invoice_id (if needed),
            counterparty,
            description,
            event_type,
            base_amount,
            gst_amount,
            total_amount,
            gst_rate,
            date,
            needs_invoice,
            confidence
        }
    """
    amount = parsed_event.get("amount") or 0.0
    event_type = parsed_event.get("event_type", "expense")
    needs_inv = parsed_event.get("needs_invoice", False)
    description = parsed_event.get("description", "")

    # Dynamic GST rate lookup based on the product/service description
    gst_info = lookup_gst_rate(description)
    gst_data = compute_gst(amount, gst_rate=gst_info["gst_rate"], gst_included=True)

    invoice_id = None
    if needs_inv:
        invoice_id = generate_invoice_id()

    return {
        "invoice_id": invoice_id,
        "counterparty": parsed_event.get("counterparty", "Unknown"),
        "description": description,
        "event_type": event_type,
        "base_amount": gst_data["base_amount"],
        "gst_amount": gst_data["gst_amount"],
        "total_amount": gst_data["total_amount"],
        "gst_rate": gst_data["gst_rate"],
        "gst_percent": gst_info["gst_percent"],
        "gst_source": gst_info["source"],
        "gst_lookup_method": gst_info["lookup_method"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "needs_invoice": needs_inv,
        "confidence": parsed_event.get("confidence", 0.0),
        "raw": parsed_event.get("raw", ""),
    }


def update_gst_summary(financial_data: dict) -> dict:
    """Update running GST totals in DB atomically."""
    return gst_update(financial_data)


def get_gst_summary() -> dict:
    return gst_get()


if __name__ == "__main__":
    sample = {
        "event_type": "income",
        "counterparty": "ABC Corp",
        "amount": 25000.0,
        "description": "Website Design",
        "needs_invoice": True,
        "confidence": 0.95,
        "raw": "Received ₹25,000 from ABC Corp for website design",
    }
    result = normalize_event(sample)
    print(json.dumps(result, indent=2))
