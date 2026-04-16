"""
finance.py — Financial Engine
Computes GST, normalizes amounts, and generates invoice metadata.
"""

from datetime import datetime
import json
import os

GST_RATE = 0.18  # 18%
DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")
GST_SUMMARY_PATH = os.path.join(DATA_DIR, "gst_summary.json")


def compute_gst(amount: float, gst_included: bool = True) -> dict:
    """
    Decompose amount into base + GST.

    Args:
        amount: Total amount (may or may not include GST)
        gst_included: If True, GST is already baked into amount

    Returns:
        { base_amount, gst_amount, total_amount, gst_rate }
    """
    if gst_included:
        base = round(amount / (1 + GST_RATE), 2)
        gst = round(amount - base, 2)
        total = round(amount, 2)
    else:
        base = round(amount, 2)
        gst = round(amount * GST_RATE, 2)
        total = round(base + gst, 2)

    return {
        "base_amount": base,
        "gst_amount": gst,
        "total_amount": total,
        "gst_rate": GST_RATE,
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

    gst_data = compute_gst(amount, gst_included=True)

    invoice_id = None
    if needs_inv:
        invoice_id = generate_invoice_id()

    return {
        "invoice_id": invoice_id,
        "counterparty": parsed_event.get("counterparty", "Unknown"),
        "description": parsed_event.get("description", ""),
        "event_type": event_type,
        "base_amount": gst_data["base_amount"],
        "gst_amount": gst_data["gst_amount"],
        "total_amount": gst_data["total_amount"],
        "gst_rate": gst_data["gst_rate"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "needs_invoice": needs_inv,
        "confidence": parsed_event.get("confidence", 0.0),
        "raw": parsed_event.get("raw", ""),
    }


def update_gst_summary(financial_data: dict) -> dict:
    """Append to running GST summary totals."""
    summary = _load_gst_summary()
    event_type = financial_data.get("event_type")

    if event_type == "income":
        summary["total_income"] = round(
            summary.get("total_income", 0) + financial_data["total_amount"], 2
        )
        summary["total_gst_collected"] = round(
            summary.get("total_gst_collected", 0) + financial_data["gst_amount"], 2
        )
    elif event_type == "expense":
        summary["total_expenses"] = round(
            summary.get("total_expenses", 0) + financial_data["total_amount"], 2
        )
        summary["total_gst_paid"] = round(
            summary.get("total_gst_paid", 0) + financial_data["gst_amount"], 2
        )

    if financial_data.get("invoice_id"):
        summary["invoice_count"] = summary.get("invoice_count", 0) + 1

    summary["net_gst_liability"] = round(
        summary.get("total_gst_collected", 0) - summary.get("total_gst_paid", 0), 2
    )
    summary["last_updated"] = datetime.now().isoformat()

    _save_gst_summary(summary)
    return summary


def get_gst_summary() -> dict:
    return _load_gst_summary()


def _load_gst_summary() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(GST_SUMMARY_PATH):
        with open(GST_SUMMARY_PATH, "r") as f:
            return json.load(f)
    return {
        "total_income": 0.0,
        "total_expenses": 0.0,
        "total_gst_collected": 0.0,
        "total_gst_paid": 0.0,
        "net_gst_liability": 0.0,
        "invoice_count": 0,
        "last_updated": None,
    }


def _save_gst_summary(summary: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(GST_SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)


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
