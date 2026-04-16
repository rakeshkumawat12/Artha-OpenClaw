"""
artha.py — Main Orchestrator
The single entry point that wires: Input → Parser → Finance → Invoice → Ledger → Trust → Output
"""

import sys
import os
import json
from datetime import datetime

# Make sibling modules importable
sys.path.insert(0, os.path.dirname(__file__))

from parser import parse
from finance import normalize_event, update_gst_summary, get_gst_summary
from invoice import generate_invoice
from ledger import append_entry, get_summary as get_ledger_summary, print_ledger_table
from trust import execute_with_verification, get_audit_log

SEPARATOR = "─" * 62


def _print_header(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def _print_parsed(parsed: dict):
    _print_header("STEP 1 · PARSER  →  Structured Event")
    print(f"  Event Type  : {parsed['event_type'].upper()}")
    print(f"  Counterparty: {parsed['counterparty']}")
    print(f"  Amount      : ₹{parsed['amount']:,.2f}" if parsed['amount'] else "  Amount      : —")
    print(f"  Description : {parsed['description']}")
    print(f"  Needs Inv.  : {parsed['needs_invoice']}")
    print(f"  Confidence  : {int(parsed['confidence'] * 100)}%")


def _print_financial(fd: dict):
    _print_header("STEP 2 · FINANCE ENGINE  →  GST + Normalization")
    print(f"  Base Amount : ₹{fd['base_amount']:,.2f}")
    print(f"  GST (18%)   : ₹{fd['gst_amount']:,.2f}")
    print(f"  Total       : ₹{fd['total_amount']:,.2f}")
    if fd.get("invoice_id"):
        print(f"  Invoice ID  : {fd['invoice_id']}")


def _print_invoice(inv: dict):
    _print_header("STEP 3 · INVOICE ENGINE  →  Document Generated")
    print(f"  Invoice ID  : {inv['invoice_id']}")
    print(f"  Client      : {inv['client_name']}")
    print(f"  Total       : ₹{inv['total_amount']:,.2f}")
    print(f"  HTML        : {inv['html_path']}")
    if inv.get("pdf_path"):
        print(f"  PDF         : {inv['pdf_path']}")
    else:
        print("  PDF         : (install weasyprint for PDF output)")
    print(f"  Status      : {inv['status'].upper()}")


def _print_ledger_entry(row: dict):
    _print_header("STEP 4 · LEDGER  →  Entry Recorded")
    print(f"  Date        : {row['date']}")
    print(f"  Type        : {row['type'].upper()}")
    print(f"  Counterparty: {row['counterparty']}")
    print(f"  Total       : ₹{float(row['total_amount']):,.2f}")
    print(f"  Status      : {row['status'].upper()}")


def _print_gst(gst: dict):
    _print_header("STEP 5 · GST TRACKER  →  Running Summary")
    print(f"  GST Collected : ₹{gst['total_gst_collected']:,.2f}")
    print(f"  GST Paid      : ₹{gst['total_gst_paid']:,.2f}")
    print(f"  Net Liability : ₹{gst['net_gst_liability']:,.2f}")


def _print_audit(entry: dict):
    _print_header("STEP 6 · VERIFICATION LOG  →  Audit Trail")
    print(f"  Action      : {entry['action']}")
    print(f"  Risk Level  : {entry['risk_level'].upper()}")
    print(f"  Status      : {entry['status'].upper()}")
    print(f"  Decision    : {entry['decision_reason']}")
    print(f"  Timestamp   : {entry['timestamp']}")


def process(raw_input: str, auto_approve: bool = True) -> dict:
    """
    Full Artha workflow for a single input message.

    Args:
        raw_input: Raw text (e.g., "Received ₹25,000 from ABC Corp for website design")
        auto_approve: If True, skip interactive approval prompts (demo mode)

    Returns:
        Summary dict with all pipeline outputs.
    """
    print(f"\n{'═' * 62}")
    print(f"  ARTHA FINOPS — Processing Signal")
    print(f"  Input: \"{raw_input}\"")
    print(f"{'═' * 62}")

    # 1. Parse
    parsed = parse(raw_input)
    _print_parsed(parsed)

    if parsed["amount"] is None:
        print("\n  [WARN] Could not extract amount. Skipping financial workflow.")
        return {"status": "skipped", "reason": "no_amount", "parsed": parsed}

    # 2. Normalize via Finance Engine
    financial_data = normalize_event(parsed)
    _print_financial(financial_data)

    # 3. Invoice Generation (if needed)
    invoice_result = None
    if financial_data["needs_invoice"] and financial_data["invoice_id"]:
        inv_outcome = execute_with_verification(
            action="generate_invoice",
            fn=lambda: generate_invoice(financial_data),
            metadata={
                "invoice_id": financial_data["invoice_id"],
                "client": financial_data["counterparty"],
                "amount": f"₹{financial_data['total_amount']:,.2f}",
            },
            auto_approve=auto_approve,
        )
        if inv_outcome["approved"]:
            invoice_result = inv_outcome["result"]
            _print_invoice(invoice_result)
        else:
            print("\n  [REJECTED] Invoice generation was rejected.")

    # 4. Ledger Update
    ledger_outcome = execute_with_verification(
        action="update_ledger",
        fn=lambda: append_entry(financial_data, status="completed"),
        metadata={
            "counterparty": financial_data["counterparty"],
            "amount": f"₹{financial_data['total_amount']:,.2f}",
            "type": financial_data["event_type"],
        },
        auto_approve=auto_approve,
    )
    ledger_row = None
    if ledger_outcome["approved"]:
        ledger_row = ledger_outcome["result"]
        _print_ledger_entry(ledger_row)
    else:
        print("\n  [REJECTED] Ledger update was rejected.")

    # 5. GST Summary Update
    gst_summary = update_gst_summary(financial_data)
    _print_gst(gst_summary)

    # 6. Final Audit Summary
    audit_entries = get_audit_log(n=2)
    if audit_entries:
        _print_audit(audit_entries[-1])

    # Final Summary
    _print_header("WORKFLOW COMPLETE  →  Summary")
    print(f"  Signal      : {parsed['event_type'].upper()} of ₹{financial_data['total_amount']:,.2f}")
    print(f"  From/To     : {financial_data['counterparty']}")
    print(f"  Invoice     : {invoice_result['invoice_id'] if invoice_result else 'N/A'}")
    print(f"  Ledger      : {'UPDATED' if ledger_row else 'SKIPPED'}")
    print(f"  Net GST Liab: ₹{gst_summary['net_gst_liability']:,.2f}")
    print(f"{'═' * 62}\n")

    return {
        "status": "completed",
        "parsed": parsed,
        "financial_data": financial_data,
        "invoice": invoice_result,
        "ledger_row": ledger_row,
        "gst_summary": gst_summary,
    }


def run_demo(auto_approve: bool = True):
    """Run the full demo with mock WhatsApp/SMS inputs."""
    mock_inputs = [
        "Received ₹25,000 from ABC Corp for website design",
        "Paid ₹4,500 for Figma subscription",
        "Payment of ₹12,000 received from Zeta Solutions for consulting",
        "Debited ₹1,200 for AWS hosting charges",
        "Send invoice to Nexus Media for ₹50,000",
        "Got paid Rs. 8000 by Priya Sharma for logo design",
        "Paid ₹3,540 for office supplies",
        "Received ₹75,000 from Vertex Tech for mobile app development",
    ]

    results = []
    for msg in mock_inputs:
        result = process(msg, auto_approve=auto_approve)
        results.append(result)

    # Final ledger view
    print(f"\n{'═' * 62}")
    print("  FINAL LEDGER STATE")
    print(f"{'═' * 62}")
    print_ledger_table()

    # Final ledger summary
    summary = get_ledger_summary()
    print(f"\n{'═' * 62}")
    print("  FINANCIAL SUMMARY")
    print(f"{'═' * 62}")
    print(f"  Total Transactions : {summary['total_transactions']}")
    print(f"  Total Income       : ₹{summary['total_income']:,.2f}")
    print(f"  Total Expenses     : ₹{summary['total_expenses']:,.2f}")
    print(f"  Net Cashflow       : ₹{summary['net_cashflow']:,.2f}")
    print(f"  GST Collected      : ₹{summary['gst_collected']:,.2f}")
    print(f"  GST Paid           : ₹{summary['gst_paid']:,.2f}")
    print(f"  Net GST Liability  : ₹{summary['net_gst_liability']:,.2f}")
    print(f"{'═' * 62}\n")

    return results


def print_ledger_cmd():
    """Print ledger as plain text (Telegram-friendly)."""
    entries = get_recent(10)
    if not entries:
        print("No transactions yet.")
        return
    print("Recent Transactions (last 10):\n")
    for e in entries:
        symbol = "+" if e["type"] == "income" else "-"
        print(f"  {e['date']}  {symbol}₹{float(e['total_amount']):,.2f}  {e['counterparty']}  [{e['type']}]")


def print_gst_cmd():
    """Print GST summary."""
    g = get_gst_summary()
    print("GST Summary:\n")
    print(f"  Collected : ₹{g['total_gst_collected']:,.2f}")
    print(f"  Paid      : ₹{g['total_gst_paid']:,.2f}")
    print(f"  Liability : ₹{g['net_gst_liability']:,.2f}")
    print(f"  Invoices  : {g['invoice_count']}")


def print_summary_cmd():
    """Print full financial summary."""
    s = get_ledger_summary()
    print("Financial Summary:\n")
    print(f"  Transactions : {s['total_transactions']}")
    print(f"  Income       : ₹{s['total_income']:,.2f}")
    print(f"  Expenses     : ₹{s['total_expenses']:,.2f}")
    print(f"  Net Cashflow : ₹{s['net_cashflow']:,.2f}")
    print(f"  GST Liability: ₹{s['net_gst_liability']:,.2f}")


if __name__ == "__main__":
    import argparse
    from ledger import get_recent

    parser_cli = argparse.ArgumentParser(description="Artha FinOps — Financial Signal Processor")
    parser_cli.add_argument("--demo", action="store_true", help="Run full demo with mock inputs")
    parser_cli.add_argument("--input", type=str, help="Process a single input message")
    parser_cli.add_argument("--interactive", action="store_true", help="Enable interactive approval prompts")
    parser_cli.add_argument("--ledger", action="store_true", help="Show recent ledger entries")
    parser_cli.add_argument("--gst", action="store_true", help="Show GST summary")
    parser_cli.add_argument("--summary", action="store_true", help="Show financial summary")
    args = parser_cli.parse_args()

    auto = not args.interactive

    if args.demo:
        run_demo(auto_approve=auto)
    elif args.input:
        process(args.input, auto_approve=auto)
    elif args.ledger:
        print_ledger_cmd()
    elif args.gst:
        print_gst_cmd()
    elif args.summary:
        print_summary_cmd()
    else:
        run_demo(auto_approve=auto)
