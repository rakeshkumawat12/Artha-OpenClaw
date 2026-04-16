"""
ledger.py — Ledger System
Appends transaction entries and maintains financial history using CSV.
"""

import csv
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")
LEDGER_PATH = os.path.join(DATA_DIR, "ledger.csv")

LEDGER_FIELDS = [
    "date",
    "type",
    "counterparty",
    "description",
    "base_amount",
    "gst_amount",
    "total_amount",
    "status",
    "invoice_id",
]


def _ensure_ledger():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
            writer.writeheader()


def append_entry(financial_data: dict, status: str = "completed") -> dict:
    """
    Append a transaction to the ledger.

    Args:
        financial_data: Output from finance.normalize_event()
        status: "completed" | "pending" | "rejected"

    Returns:
        The ledger row that was written.
    """
    _ensure_ledger()
    row = {
        "date": financial_data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "type": financial_data.get("event_type", "unknown"),
        "counterparty": financial_data.get("counterparty", "Unknown"),
        "description": financial_data.get("description", ""),
        "base_amount": financial_data.get("base_amount", 0.0),
        "gst_amount": financial_data.get("gst_amount", 0.0),
        "total_amount": financial_data.get("total_amount", 0.0),
        "status": status,
        "invoice_id": financial_data.get("invoice_id", ""),
    }
    with open(LEDGER_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        writer.writerow(row)
    return row


def read_all() -> list[dict]:
    """Return all ledger entries as a list of dicts."""
    _ensure_ledger()
    with open(LEDGER_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_summary() -> dict:
    """Compute running totals from the ledger."""
    entries = read_all()
    total_income = 0.0
    total_expenses = 0.0
    gst_collected = 0.0
    gst_paid = 0.0

    for entry in entries:
        try:
            total = float(entry.get("total_amount", 0))
            gst = float(entry.get("gst_amount", 0))
            if entry["type"] == "income":
                total_income += total
                gst_collected += gst
            elif entry["type"] == "expense":
                total_expenses += total
                gst_paid += gst
        except (ValueError, KeyError):
            continue

    return {
        "total_transactions": len(entries),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "net_cashflow": round(total_income - total_expenses, 2),
        "gst_collected": round(gst_collected, 2),
        "gst_paid": round(gst_paid, 2),
        "net_gst_liability": round(gst_collected - gst_paid, 2),
    }


def get_recent(n: int = 5) -> list[dict]:
    """Return the last N entries."""
    return read_all()[-n:]


def print_ledger_table():
    """Pretty-print the ledger as a table."""
    entries = read_all()
    if not entries:
        print("  [Ledger is empty]")
        return

    col_widths = {
        "date": 12, "type": 9, "counterparty": 20,
        "description": 24, "total_amount": 12, "status": 10, "invoice_id": 14
    }
    header_keys = ["date", "type", "counterparty", "description", "total_amount", "status", "invoice_id"]
    header = "  ".join(k.upper().ljust(col_widths[k]) for k in header_keys)
    print(header)
    print("-" * len(header))
    for e in entries:
        row = "  ".join(
            str(e.get(k, "")).ljust(col_widths[k]) for k in header_keys
        )
        print(row)


if __name__ == "__main__":
    sample = {
        "date": "2026-04-16",
        "event_type": "income",
        "counterparty": "ABC Corp",
        "description": "Website Design",
        "base_amount": 21186.44,
        "gst_amount": 3813.56,
        "total_amount": 25000.0,
        "invoice_id": "INV-2026-0001",
    }
    row = append_entry(sample)
    print("Appended:", row)
    print("\nLedger Summary:", get_summary())
    print("\nAll Entries:")
    print_ledger_table()
