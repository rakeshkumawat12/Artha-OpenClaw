# Artha FinOps

Converts plain-text payment messages (WhatsApp/SMS/Telegram) into GST invoices, ledger entries, and financial summaries — automatically.

---

## Setup after cloning

### 1. Prerequisites

Make sure you have Python 3.9+ installed:
```bash
python3 --version
```

### 2. Clone the repo
```bash
git clone <repo-url>
cd openclaw
```

### 3. Install dependencies
```bash
pip3 install -r requirements.txt
```

> `weasyprint` is optional — only needed for PDF invoice generation. If it fails to install, HTML invoices still work fine.

### 4. Set up the database

Run this once — it creates `data/artha.db` and migrates any existing data:
```bash
python3 skills/artha-finops/db.py
```

You should see:
```
[DB] Migration complete — ledger: 0 rows, audit: 0 entries
```

### 5. Test it works (CLI)
```bash
python3 skills/artha-finops/artha.py --input "Received ₹25,000 from ABC Corp for website design"
```

If you see GST breakdown, ledger entry, and audit trail — you're good.

---

## Telegram Bot Setup

### Step 1 — Create your bot

1. Open Telegram → search `@BotFather`
2. Send `/newbot`
3. Follow the prompts — choose a name and username
4. Copy the **token** it gives you (looks like `123456789:ABCdefGHI...`)

### Step 2 — Add your token

Create a `.env` file in the project root:
```bash
echo 'TELEGRAM_BOT_TOKEN=your_token_here' > .env
```

Or set it as an environment variable:
```bash
export TELEGRAM_BOT_TOKEN=your_token_here
```

### Step 3 — Run the bot
```bash
python3 skills/artha-finops/telegram_bot.py
```

You should see:
```
Artha FinOps bot is running. Press Ctrl+C to stop.
```

Now open Telegram, find your bot, send `/start` and start typing payments.

---

## Using Artha on Telegram

Just send natural messages:

```
Received ₹25,000 from ABC Corp for website design
Paid ₹4,500 for Figma subscription
Send invoice to Nexus Media for ₹50,000
Got paid Rs. 8000 by Priya Sharma for logo design
```

**Commands:**
```
/start    — welcome + instructions
/ledger   — recent 10 transactions
/gst      — GST collected / paid / net liability
/summary  — full income, expenses, cashflow
/pending  — open invoices awaiting payment
```

---

## Using Artha on CLI

**Single message:**
```bash
python3 skills/artha-finops/artha.py --input "Received ₹25,000 from ABC Corp for website design"
```

**Full demo (8 mock transactions):**
```bash
python3 skills/artha-finops/artha.py --demo
```

**Interactive mode (manual approval for each step):**
```bash
python3 skills/artha-finops/artha.py --input "Received ₹25,000 from ABC Corp" --interactive
```

**View reports:**
```bash
python3 skills/artha-finops/artha.py --ledger     # recent transactions
python3 skills/artha-finops/artha.py --gst        # GST summary
python3 skills/artha-finops/artha.py --summary    # full financial summary
```

---

## Project Structure

```
openclaw/
├── skills/artha-finops/
│   ├── artha.py          # main orchestrator — entry point
│   ├── parser.py         # extracts amount, counterparty, type from text
│   ├── finance.py        # GST computation and normalization
│   ├── gst_lookup.py     # auto-detects GST rate per product/service
│   ├── invoice.py        # generates HTML/PDF invoices
│   ├── ledger.py         # transaction ledger interface
│   ├── trust.py          # payment verification and audit logging
│   ├── db.py             # SQLite database layer (all storage)
│   ├── security.py       # whitelist, rate limiting, input sanitization
│   └── telegram_bot.py   # Telegram bot interface
├── data/
│   ├── artha.db          # SQLite database (created on first run)
│   └── clients.json      # known client profiles
├── templates/
│   └── invoice_template.html
├── invoices/             # generated invoice files (HTML/PDF)
└── requirements.txt
```

---

## Security

Every message passes through a security layer before touching the pipeline:

```
Telegram message
      ↓
  @secured decorator  ← sits in front of EVERY handler
      ↓
  ┌─────────────────────────────────────┐
  │         security_gate()            │
  │                                    │
  │  1. Whitelist check                │
  │     Is this user ID allowed?       │
  │     No → blocked, logged, denied   │
  │                                    │
  │  2. Rate limit                     │
  │     >10 msgs/min? → blocked        │
  │                                    │
  │  3. Input size                     │
  │     >500 chars? → blocked          │
  │                                    │
  │  4. Pattern scan                   │
  │     SQL injection → blocked        │
  │     XSS → blocked                  │
  │     Prompt injection → blocked     │
  │     Template injection → blocked   │
  │                                    │
  │  5. Sanitize                       │
  │     Strip control characters       │
  │     Normalize whitespace           │
  └─────────────────────────────────────┘
      ↓ only clean, verified input passes
  Artha pipeline
```

### Activating the whitelist

Find your Telegram user ID by messaging `@userinfobot` on Telegram, then add it to `.env`:

```bash
ARTHA_ALLOWED_USERS=123456789

# Multiple users (e.g. you + accountant):
ARTHA_ALLOWED_USERS=123456789,987654321
```

### Lock down the DB file

```bash
chmod 600 data/artha.db
echo ".env" >> .gitignore
```

Every blocked attempt is logged to the audit trail with a hash of what was sent — no raw content stored.

---

## What Artha does automatically

- Detects whether a message is income, expense, or invoice request
- Looks up the correct GST rate for the product/service mentioned
- Checks incoming payments against open invoices — blocks if amounts don't match
- Generates a GST-compliant invoice (HTML + PDF if weasyprint installed)
- Records everything in SQLite with full audit trail
- Never auto-approves invoices — payment must be verified first

---

## Requirements

- Python 3.9+
- `jinja2` — invoice templating
- `python-telegram-bot` — Telegram interface
- `weasyprint` — PDF generation (optional)
