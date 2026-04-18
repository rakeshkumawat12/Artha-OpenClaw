"""
ledger.py — Ledger System
Backed by SQLite via db.py. CSV file kept as a read-only export fallback.
"""

from typing import Optional
from db import (
    ledger_insert,
    ledger_find_open_invoice,
    ledger_get_recent,
    ledger_get_summary,
    ledger_get_all,
    ledger_get_pending,
)


def append_entry(financial_data: dict, status: str = "completed") -> dict:
    """Insert a transaction into the DB and return the written row."""
    return ledger_insert(financial_data, status=status)


def read_all() -> list[dict]:
    """Return all ledger entries."""
    return ledger_get_all()


def get_summary() -> dict:
    """Compute running totals directly from DB — always accurate."""
    return ledger_get_summary()


def find_open_invoice(counterparty: str) -> Optional[dict]:
    """Find the most recent pending invoice for a counterparty."""
    return ledger_find_open_invoice(counterparty)


def get_recent(n: int = 10) -> list[dict]:
    """Return the last N entries."""
    return ledger_get_recent(n)


def print_ledger_table():
    """Pretty-print the ledger as a table."""
    entries = ledger_get_all()
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
