"""
invoice.py — Invoice Engine
Generates HTML invoices and optionally converts to PDF.
"""

import os
import json
from datetime import datetime

try:
    from jinja2 import Environment, FileSystemLoader
    JINJA_AVAILABLE = True
except ImportError:
    JINJA_AVAILABLE = False

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../../templates")
INVOICES_DIR = os.path.join(os.path.dirname(__file__), "../../invoices")
DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")
CLIENTS_PATH = os.path.join(DATA_DIR, "clients.json")

# Mock seller profile
SELLER_PROFILE = {
    "name": "Artha Consulting LLP",
    "email": "billing@artha.consulting",
    "gstin": "29AABCA1234C1ZK",
    "address": "Bengaluru, Karnataka - 560001",
}


def load_clients() -> dict:
    if os.path.exists(CLIENTS_PATH):
        with open(CLIENTS_PATH, "r") as f:
            data = json.load(f)
        return {c["name"].lower(): c for c in data.get("clients", [])}
    return {}


def resolve_client(counterparty: str) -> dict:
    """Look up client by name or return a generated stub."""
    clients = load_clients()
    key = counterparty.lower().strip()
    # Fuzzy match: check if any known client name is substring
    for client_key, client_data in clients.items():
        if client_key in key or key in client_key:
            return client_data
    # Generate stub
    return {
        "name": counterparty,
        "email": f"accounts@{counterparty.lower().replace(' ', '')}.com",
        "address": "India",
        "gstin": "UNREGISTERED",
    }


def render_invoice_html(financial_data: dict) -> str:
    """Render the invoice HTML using Jinja2 template."""
    gst_amount = financial_data["gst_amount"]
    cgst = round(gst_amount / 2, 2)
    sgst = round(gst_amount / 2, 2)

    client = resolve_client(financial_data["counterparty"])

    context = {
        "invoice_id": financial_data["invoice_id"],
        "date": financial_data["date"],
        "seller_name": SELLER_PROFILE["name"],
        "seller_email": SELLER_PROFILE["email"],
        "seller_gstin": SELLER_PROFILE["gstin"],
        "client_name": client["name"],
        "client_email": client.get("email", ""),
        "client_address": client.get("address", "India"),
        "description": financial_data["description"],
        "base_amount": f"{financial_data['base_amount']:,.2f}",
        "cgst_rate": "9",
        "sgst_rate": "9",
        "cgst_amount": f"{cgst:,.2f}",
        "sgst_amount": f"{sgst:,.2f}",
        "total_amount": f"{financial_data['total_amount']:,.2f}",
    }

    if JINJA_AVAILABLE:
        env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
        template = env.get_template("invoice_template.html")
        return template.render(**context)
    else:
        # Fallback: simple string replacement
        template_path = os.path.join(TEMPLATES_DIR, "invoice_template.html")
        with open(template_path, "r") as f:
            html = f.read()
        for key, val in context.items():
            html = html.replace("{{ " + key + " }}", str(val))
        return html


def generate_invoice(financial_data: dict) -> dict:
    """
    Generate an invoice file and return its metadata.

    Returns:
        {
            invoice_id, html_path, pdf_path (if available),
            client_name, total_amount, date
        }
    """
    os.makedirs(INVOICES_DIR, exist_ok=True)
    invoice_id = financial_data["invoice_id"]

    html_content = render_invoice_html(financial_data)
    html_path = os.path.join(INVOICES_DIR, f"{invoice_id}.html")
    with open(html_path, "w") as f:
        f.write(html_content)

    pdf_path = None
    pdf_path = _try_generate_pdf(html_content, invoice_id)

    client = resolve_client(financial_data["counterparty"])
    return {
        "invoice_id": invoice_id,
        "html_path": html_path,
        "pdf_path": pdf_path,
        "client_name": client["name"],
        "total_amount": financial_data["total_amount"],
        "date": financial_data["date"],
        "status": "generated",
    }


def _try_generate_pdf(html_content: str, invoice_id: str):
    """Attempt PDF generation via weasyprint, fall back gracefully."""
    try:
        from weasyprint import HTML
        pdf_path = os.path.join(INVOICES_DIR, f"{invoice_id}.pdf")
        HTML(string=html_content).write_pdf(pdf_path)
        return pdf_path
    except ImportError:
        return None
    except Exception:
        return None


if __name__ == "__main__":
    sample_financial = {
        "invoice_id": "INV-2026-0001",
        "counterparty": "ABC Corp",
        "description": "Website Design",
        "event_type": "income",
        "base_amount": 21186.44,
        "gst_amount": 3813.56,
        "total_amount": 25000.0,
        "gst_rate": 0.18,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "needs_invoice": True,
        "confidence": 0.95,
    }
    result = generate_invoice(sample_financial)
    print(json.dumps(result, indent=2))
