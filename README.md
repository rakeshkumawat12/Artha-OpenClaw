# Artha FinOps

Example: "Received 35,000 from LedgerPe for building"

Converts raw financial messages (WhatsApp/SMS) into invoices, ledger entries, and GST summaries.

## Setup

```bash
pip3 install jinja2
```

## Run

**Full demo (8 mock inputs):**
```bash
python3 skills/artha-finops/artha.py --demo
```

**Single message:**
```bash
python3 skills/artha-finops/artha.py --input "Received ₹25,000 from ABC Corp for website design"
```

**View ledger:**
```bash
python3 skills/artha-finops/artha.py --ledger
```

**GST summary:**
```bash
python3 skills/artha-finops/artha.py --gst
```

**Financial summary:**
```bash
python3 skills/artha-finops/artha.py --summary
```

## Output

- Invoices → `invoices/INV-YYYY-XXXX.html`
- Ledger → `data/ledger.csv`
- GST state → `data/gst_summary.json`
- Audit log → `data/audit_log.jsonl`
