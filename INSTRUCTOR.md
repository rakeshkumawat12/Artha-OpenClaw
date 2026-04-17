# Artha FinOps — Project Overview

## What is this?

Artha is a local-first financial assistant built on top of OpenClaw.

You send a casual message on Telegram like a human would:
> "Received ₹35,000 from LedgerPe for building"

Artha automatically creates an invoice, records the transaction, calculates GST, and replies back on Telegram — all running on your laptop.

---

## Problem it solves

Freelancers and small businesses receive payments via WhatsApp, UPI, SMS — but tracking them is manual and messy.

- No invoice gets created on time
- GST is calculated at the end of the month (reactively)
- Ledger is maintained in Excel or not at all

Artha converts unstructured messages into structured financial actions instantly.

---

## How it connects to OpenClaw

```
Telegram message
      ↓
OpenClaw (running on your laptop)
      ↓
AI reads SKILL.md → knows what Artha is
      ↓
Runs: python3 artha.py --input "your message"
      ↓
Invoice + Ledger + GST updated
      ↓
Reply sent back to Telegram
```

OpenClaw is the runtime. Artha is the skill. Your Telegram is the interface.

---

## File Structure

```
openclaw/
├── skills/artha-finops/
│   ├── artha.py          ← main orchestrator, run this
│   ├── parser.py         ← extracts meaning from raw text
│   ├── finance.py        ← GST calculation, invoice ID
│   ├── invoice.py        ← generates HTML invoice
│   ├── ledger.py         ← records transactions to CSV
│   └── trust.py          ← risk check + audit logging
├── data/
│   ├── ledger.csv        ← all transactions
│   ├── clients.json      ← mock client data
│   ├── gst_summary.json  ← running GST totals
│   └── audit_log.jsonl   ← every action logged
├── invoices/             ← generated invoice files
├── templates/
│   └── invoice_template.html
├── README.md
└── INSTRUCTOR.md
```

---

## What each Python file does

### parser.py
Reads raw text. Extracts amount, type, and counterparty using regex and keywords.
```
"Received ₹35,000 from LedgerPe for building"
→ { event_type: income, amount: 35000, counterparty: LedgerPe }
```

### finance.py
Does the math. Splits amount into base + 18% GST. Generates invoice ID.
```
35000 / 1.18 = 29,661  ← base
35000 - 29661 = 5,339  ← GST
→ INV-2026-0001
```

### invoice.py
Fills the HTML template with real data. Saves it as a file.
```
→ invoices/INV-2026-0001.html
```

### ledger.py
Appends one row to ledger.csv. Permanent transaction record.
```
2026-04-17, income, LedgerPe, Building, 29661, 5339, 35000
```

### trust.py
Checks risk level before any sensitive action. Logs every decision.
```
generate_invoice → low risk  → auto approved
send_invoice     → high risk → needs approval
→ audit_log.jsonl
```

### artha.py
The main file. Calls all above files in order. This is the only file you run.
```
parse → finance → invoice → ledger → trust → output
```

---

## Execution Flow (step by step)

1. You type on Telegram: `"Received ₹35,000 from LedgerPe for building"`
2. OpenClaw receives the message via Telegram bot
3. AI reads `SKILL.md` → matches trigger keywords → runs artha.py
4. `parser.py` extracts: income, ₹35,000, LedgerPe
5. `finance.py` computes: base ₹29,661 + GST ₹5,339
6. `invoice.py` generates: `invoices/INV-2026-0001.html`
7. `ledger.py` records: new row in `data/ledger.csv`
8. `trust.py` logs: action approved in `audit_log.jsonl`
9. OpenClaw sends reply back to Telegram with summary

---

## Commands

```bash
# Full demo with 8 mock inputs
python3 skills/artha-finops/artha.py --demo

# Single message
python3 skills/artha-finops/artha.py --input "Received ₹35,000 from LedgerPe for building"

# View last 10 transactions
python3 skills/artha-finops/artha.py --ledger

# GST summary
python3 skills/artha-finops/artha.py --gst

# Full financial summary
python3 skills/artha-finops/artha.py --summary
```

---

## Supported message types

| Message | What happens |
|---------|-------------|
| "Received ₹X from Y" | Income recorded, invoice generated if needed |
| "Paid ₹X for Y" | Expense recorded |
| "Send invoice to Y for ₹X" | Invoice generated and recorded |
| "Show ledger" | Last 10 transactions returned |
| "GST summary" | Running GST totals returned |
| "Financial summary" | Income, expenses, cashflow returned |

---

## Data files generated

| File | What's inside |
|------|--------------|
| `data/ledger.csv` | Every transaction ever recorded |
| `data/gst_summary.json` | Running GST collected, paid, liability |
| `data/audit_log.jsonl` | Every action with timestamp and approval status |
| `invoices/INV-*.html` | Generated invoice documents |

---

## OpenClaw integration files

| File | Purpose |
|------|---------|
| `~/.openclaw/workspace/skills/artha-finops/SKILL.md` | Tells OpenClaw when and how to trigger Artha |
| `~/.openclaw/workspace/AGENTS.md` | Tells OpenClaw to load Artha skill on every session |
| `~/.openclaw/openclaw.json` | OpenClaw config: Telegram bot token, API key, model |

---

## Setup to run with OpenClaw + Telegram

```bash
# 1. Install dependency
pip3 install jinja2

# 2. Set Node version
nvm use 22.14.0

# 3. Set OpenAI API key in OpenClaw
openclaw config set auth.profiles.openai:default.apiKey YOUR-KEY

# 4. Restart gateway
openclaw gateway restart

# 5. Message your Telegram bot
# "Received ₹35,000 from LedgerPe for building"
```

---

## Design principles

- **Local-first** — everything runs on your machine, no cloud
- **No forms** — just talk naturally, like WhatsApp
- **Continuous GST** — always up to date, not end-of-month panic
- **Verified execution** — sensitive actions need approval before running
- **Audit trail** — every action logged with timestamp

---

## What this is NOT

- Not production-ready accounting software
- No real WhatsApp/UPI API integration
- No bank sync
- GST logic is simplified (18% flat, CGST + SGST split)

This is a focused demo showing how OpenClaw can turn unstructured financial messages into structured, automated workflows.
