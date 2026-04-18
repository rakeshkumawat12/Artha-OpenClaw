"""
telegram_bot.py — Artha FinOps Telegram Interface
Connects the Artha pipeline to Telegram.

Commands:
  /start        — welcome message
  /ledger       — recent 10 transactions
  /gst          — GST summary
  /summary      — full financial summary
  /pending      — all open (pending) invoices

Any other message is treated as a financial input and run through the pipeline.

Setup:
  pip install python-telegram-bot
  Set TELEGRAM_BOT_TOKEN in environment or .env file.
"""

import os
import sys
import logging
from datetime import datetime

# Make sibling modules importable
sys.path.insert(0, os.path.dirname(__file__))

try:
    from telegram import Update, constants
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
except ImportError:
    print("ERROR: python-telegram-bot not installed.")
    print("Run: pip install python-telegram-bot")
    sys.exit(1)

from finance import normalize_event
from parser import parse
from invoice import generate_invoice
from ledger import append_entry, get_summary as get_ledger_summary, get_recent, find_open_invoice
from trust import verify_payment_amount, execute_with_verification, get_audit_log
from finance import get_gst_summary
from security import secured, startup_security_check

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------

def _fmt_verification_alert(financial_data: dict, payment_check: dict) -> str:
    """Format a payment mismatch alert for Telegram."""
    discrepancy = payment_check["discrepancy"]
    received = payment_check["parsed_amount"]
    expected = payment_check["expected_amount"]
    source = payment_check.get("expected_source", "—")
    counterparty = financial_data["counterparty"]

    return (
        f"🚨 *PAYMENT MISMATCH — ACTION REQUIRED*\n"
        f"{'─' * 35}\n"
        f"👤 *Counterparty:* {counterparty}\n"
        f"💰 *Received:*     ₹{received:,.2f}\n"
        f"📋 *Expected:*     ₹{expected:,.2f}\n"
        f"⚠️ *Discrepancy:* ₹{discrepancy:,.2f}\n"
        f"📄 *Source:* {source}\n"
        f"{'─' * 35}\n"
        f"❌ Invoice and ledger update *BLOCKED*.\n"
        f"Please confirm the correct amount with {counterparty} before resubmitting."
    )


def _fmt_invoice_raised(financial_data: dict) -> str:
    """Format an invoice-raised confirmation for Telegram."""
    return (
        f"🧾 *NEW INVOICE RAISED*\n"
        f"{'─' * 35}\n"
        f"📋 *Invoice ID:*   `{financial_data['invoice_id']}`\n"
        f"👤 *Client:*       {financial_data['counterparty']}\n"
        f"📝 *Description:*  {financial_data['description']}\n"
        f"💵 *Base Amount:*  ₹{financial_data['base_amount']:,.2f}\n"
        f"🏛️ *GST ({financial_data['gst_percent']}%):*    ₹{financial_data['gst_amount']:,.2f}\n"
        f"💰 *Total:*        ₹{financial_data['total_amount']:,.2f}\n"
        f"📅 *Date:*         {financial_data['date']}\n"
        f"{'─' * 35}\n"
        f"⏳ Status: *PENDING* — awaiting payment from {financial_data['counterparty']}"
    )


def _fmt_payment_confirmed(financial_data: dict, payment_check: dict) -> str:
    """Format a successful payment confirmation for Telegram."""
    source = payment_check.get("expected_source", "—")
    return (
        f"✅ *PAYMENT VERIFIED & RECORDED*\n"
        f"{'─' * 35}\n"
        f"👤 *From:*         {financial_data['counterparty']}\n"
        f"💰 *Amount:*       ₹{financial_data['total_amount']:,.2f}\n"
        f"📝 *Description:*  {financial_data['description']}\n"
        f"🏛️ *GST ({financial_data['gst_percent']}%):*    ₹{financial_data['gst_amount']:,.2f}\n"
        f"📄 *Matched:*      {source}\n"
        f"{'─' * 35}\n"
        f"📒 Ledger updated — status: *COMPLETED*"
    )


def _fmt_expense_recorded(financial_data: dict) -> str:
    """Format an expense recording confirmation for Telegram."""
    return (
        f"📤 *EXPENSE RECORDED*\n"
        f"{'─' * 35}\n"
        f"👤 *To:*           {financial_data['counterparty']}\n"
        f"💸 *Amount:*       ₹{financial_data['total_amount']:,.2f}\n"
        f"📝 *Description:*  {financial_data['description']}\n"
        f"🏛️ *GST ({financial_data['gst_percent']}%):*    ₹{financial_data['gst_amount']:,.2f}\n"
        f"{'─' * 35}\n"
        f"📒 Ledger updated — status: *COMPLETED*"
    )


def _fmt_pending_invoices(pending: list) -> str:
    """Format list of pending invoices for Telegram."""
    if not pending:
        return "✅ No open invoices. All payments received."

    lines = ["📋 *OPEN INVOICES — AWAITING PAYMENT*\n" + "─" * 35]
    for e in pending:
        lines.append(
            f"📄 `{e['invoice_id']}`\n"
            f"   👤 {e['counterparty']}\n"
            f"   💰 ₹{float(e['total_amount']):,.2f}\n"
            f"   📅 {e['date']}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Core pipeline (bot-facing, returns formatted message strings)
# ---------------------------------------------------------------------------

def run_pipeline(raw_input: str) -> str:
    """
    Run Artha pipeline for a raw text input.
    Returns a Telegram-formatted string to send back to the user.
    """
    parsed = parse(raw_input)

    if parsed["amount"] is None:
        return (
            "⚠️ Could not extract an amount from your message.\n"
            "Try: _\"Received ₹25,000 from ABC Corp for website design\"_"
        )

    financial_data = normalize_event(parsed)
    event_type = financial_data["event_type"]

    # --- INVOICE REQUEST ---
    if event_type == "invoice_request" and financial_data.get("invoice_id"):
        append_entry(financial_data, status="pending")
        return _fmt_invoice_raised(financial_data)

    # --- INCOME: verify against open invoice ---
    if event_type == "income":
        parsed_amount = financial_data["total_amount"]
        open_invoice = find_open_invoice(financial_data["counterparty"])

        if open_invoice:
            expected_amount = float(open_invoice["total_amount"])
            expected_source = f"Open invoice {open_invoice['invoice_id']} raised on {open_invoice['date']}"
        else:
            expected_amount = parsed_amount
            expected_source = "No open invoice — fresh payment confirmation"

        payment_check = verify_payment_amount(parsed_amount, expected_amount)
        payment_check["expected_source"] = expected_source

        if not payment_check["verified"]:
            # Log the failed attempt to audit trail
            execute_with_verification(
                action="verify_payment",
                fn=lambda: payment_check,
                metadata={
                    "counterparty": financial_data["counterparty"],
                    "parsed_amount": f"₹{parsed_amount:,.2f}",
                    "expected_amount": f"₹{expected_amount:,.2f}",
                    "discrepancy": f"₹{payment_check['discrepancy']:,.2f}",
                },
                auto_approve=True,  # auto-log but payment_check.verified=False still blocks
            )
            return _fmt_verification_alert(financial_data, payment_check)

        # Payment verified — record as completed
        append_entry(financial_data, status="completed")
        return _fmt_payment_confirmed(financial_data, payment_check)

    # --- EXPENSE ---
    if event_type == "expense":
        append_entry(financial_data, status="completed")
        return _fmt_expense_recorded(financial_data)

    return "⚠️ Could not classify this transaction. Please rephrase."


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@secured
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to Artha FinOps*\n"
        "─────────────────────────────\n"
        "Just send me a payment message and I'll handle the rest:\n\n"
        "_\"Received ₹25,000 from ABC Corp for website design\"_\n"
        "_\"Paid ₹4,500 for Figma subscription\"_\n"
        "_\"Send invoice to Nexus Media for ₹50,000\"_\n\n"
        "*Commands:*\n"
        "/ledger — recent transactions\n"
        "/gst — GST summary\n"
        "/summary — financial overview\n"
        "/pending — open invoices awaiting payment",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


@secured
async def cmd_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entries = get_recent(10)
    if not entries:
        await update.message.reply_text("📒 No transactions yet.")
        return

    lines = ["📒 *RECENT TRANSACTIONS*\n" + "─" * 35]
    for e in entries:
        symbol = "📥" if e["type"] == "income" else "📤"
        status_icon = "✅" if e["status"] == "completed" else "⏳"
        lines.append(
            f"{symbol} {e['date']}  {status_icon}\n"
            f"   {e['counterparty']}\n"
            f"   ₹{float(e['total_amount']):,.2f}  [{e['type']}]"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=constants.ParseMode.MARKDOWN,
    )


@secured
async def cmd_gst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = get_gst_summary()
    msg = (
        f"🏛️ *GST SUMMARY*\n"
        f"{'─' * 35}\n"
        f"📥 Collected:  ₹{g['total_gst_collected']:,.2f}\n"
        f"📤 Paid:       ₹{g['total_gst_paid']:,.2f}\n"
        f"⚖️ Net Liability: ₹{g['net_gst_liability']:,.2f}\n"
        f"🧾 Invoices:   {g['invoice_count']}\n"
        f"🕐 Updated:    {g.get('last_updated', '—')[:19] if g.get('last_updated') else '—'}"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


@secured
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_ledger_summary()
    msg = (
        f"📊 *FINANCIAL SUMMARY*\n"
        f"{'─' * 35}\n"
        f"🔢 Transactions:  {s['total_transactions']}\n"
        f"📥 Total Income:  ₹{s['total_income']:,.2f}\n"
        f"📤 Total Expenses:₹{s['total_expenses']:,.2f}\n"
        f"💰 Net Cashflow:  ₹{s['net_cashflow']:,.2f}\n"
        f"🏛️ GST Collected: ₹{s['gst_collected']:,.2f}\n"
        f"🏛️ GST Paid:      ₹{s['gst_paid']:,.2f}\n"
        f"⚖️ GST Liability: ₹{s['net_gst_liability']:,.2f}"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


@secured
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ledger import read_all
    all_entries = read_all()
    pending = [e for e in all_entries if e.get("status", "").lower() == "pending"]
    msg = _fmt_pending_invoices(pending)
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)


@secured
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    logger.info(f"Received from {update.effective_user.id}: [sanitized]")

    await update.message.reply_text("⏳ Processing...")

    try:
        response = run_pipeline(raw)
    except Exception as e:
        logger.exception("Pipeline error")
        response = f"❌ Error processing your message:\n`{str(e)}`"

    await update.message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        # Try loading from .env file in project root
        env_path = os.path.join(os.path.dirname(__file__), "../../.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set.")
        print("Set it in environment: export TELEGRAM_BOT_TOKEN=your_token")
        print("Or add to .env file:   TELEGRAM_BOT_TOKEN=your_token")
        sys.exit(1)

    # Run startup security checks before accepting any messages
    print("\n── Security Checks ──────────────────────────────────")
    warnings = startup_security_check()
    if warnings:
        for w in warnings:
            print(f"  {w}")
    else:
        print("  All checks passed.")
    print("─────────────────────────────────────────────────────\n")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ledger", cmd_ledger))
    app.add_handler(CommandHandler("gst", cmd_gst))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Artha FinOps bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
