"""
db.py — SQLite Database Layer
Single source of truth for all Artha data.
Replaces: ledger.csv, gst_summary.json, audit_log.jsonl

Tables:
  ledger       — all transactions (income / expense / invoice_request)
  gst_summary  — running GST totals (single-row, updated in place)
  audit_log    — immutable append-only action log
"""

import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "../../data/artha.db")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    """
    Context manager that yields a connection with:
    - WAL mode (safe concurrent reads + writes)
    - Row factory so rows come back as dicts
    - Foreign key enforcement
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ledger (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT NOT NULL,
                type            TEXT NOT NULL CHECK(type IN ('income','expense','invoice_request')),
                counterparty    TEXT NOT NULL,
                description     TEXT,
                base_amount     REAL NOT NULL DEFAULT 0,
                gst_amount      REAL NOT NULL DEFAULT 0,
                total_amount    REAL NOT NULL DEFAULT 0,
                gst_rate        REAL NOT NULL DEFAULT 0.18,
                gst_percent     INTEGER NOT NULL DEFAULT 18,
                gst_source      TEXT,
                status          TEXT NOT NULL DEFAULT 'pending'
                                    CHECK(status IN ('pending','completed','rejected')),
                invoice_id      TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ledger_counterparty
                ON ledger(counterparty);
            CREATE INDEX IF NOT EXISTS idx_ledger_status
                ON ledger(status);
            CREATE INDEX IF NOT EXISTS idx_ledger_date
                ON ledger(date);
            CREATE INDEX IF NOT EXISTS idx_ledger_invoice_id
                ON ledger(invoice_id);

            CREATE TABLE IF NOT EXISTS gst_summary (
                id                  INTEGER PRIMARY KEY CHECK(id = 1),
                total_income        REAL NOT NULL DEFAULT 0,
                total_expenses      REAL NOT NULL DEFAULT 0,
                total_gst_collected REAL NOT NULL DEFAULT 0,
                total_gst_paid      REAL NOT NULL DEFAULT 0,
                net_gst_liability   REAL NOT NULL DEFAULT 0,
                invoice_count       INTEGER NOT NULL DEFAULT 0,
                last_updated        TEXT
            );

            -- Ensure single-row GST summary always exists
            INSERT OR IGNORE INTO gst_summary (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS audit_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
                action          TEXT NOT NULL,
                risk_level      TEXT NOT NULL,
                status          TEXT NOT NULL,
                decision_reason TEXT,
                details         TEXT   -- JSON blob
            );

            CREATE INDEX IF NOT EXISTS idx_audit_action
                ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_log(timestamp);
        """)


# ---------------------------------------------------------------------------
# Ledger operations
# ---------------------------------------------------------------------------

def ledger_insert(financial_data: dict, status: str = "pending") -> dict:
    """Insert a transaction and return the full row as a dict."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO ledger
                (date, type, counterparty, description,
                 base_amount, gst_amount, total_amount,
                 gst_rate, gst_percent, gst_source,
                 status, invoice_id)
            VALUES
                (:date, :type, :counterparty, :description,
                 :base_amount, :gst_amount, :total_amount,
                 :gst_rate, :gst_percent, :gst_source,
                 :status, :invoice_id)
            """,
            {
                "date": financial_data.get("date", datetime.now().strftime("%Y-%m-%d")),
                "type": financial_data.get("event_type", "expense"),
                "counterparty": financial_data.get("counterparty", "Unknown"),
                "description": financial_data.get("description", ""),
                "base_amount": financial_data.get("base_amount", 0.0),
                "gst_amount": financial_data.get("gst_amount", 0.0),
                "total_amount": financial_data.get("total_amount", 0.0),
                "gst_rate": financial_data.get("gst_rate", 0.18),
                "gst_percent": financial_data.get("gst_percent", 18),
                "gst_source": financial_data.get("gst_source", ""),
                "status": status,
                "invoice_id": financial_data.get("invoice_id", ""),
            },
        )
        row = conn.execute(
            "SELECT * FROM ledger WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def ledger_update_status(invoice_id: str, status: str):
    """Update status of a ledger entry by invoice_id."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE ledger SET status = ? WHERE invoice_id = ?",
            (status, invoice_id),
        )


def ledger_find_open_invoice(counterparty: str) -> Optional[dict]:
    """Find the most recent pending invoice for a counterparty."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM ledger
            WHERE type = 'income'
              AND status = 'pending'
              AND invoice_id != ''
              AND lower(counterparty) LIKE lower(?)
            ORDER BY date DESC, id DESC
            LIMIT 1
            """,
            (f"%{counterparty.strip()}%",),
        ).fetchone()
        return dict(row) if row else None


def ledger_get_recent(n: int = 10) -> list[dict]:
    """Return last N ledger entries."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def ledger_get_pending() -> list[dict]:
    """Return all pending entries (open invoices)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ledger WHERE status = 'pending' ORDER BY date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def ledger_get_summary() -> dict:
    """Compute running totals directly from DB — always accurate."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                        AS total_transactions,
                COALESCE(SUM(CASE WHEN type='income'
                    THEN total_amount ELSE 0 END), 0)          AS total_income,
                COALESCE(SUM(CASE WHEN type='expense'
                    THEN total_amount ELSE 0 END), 0)          AS total_expenses,
                COALESCE(SUM(CASE WHEN type='income'
                    THEN gst_amount ELSE 0 END), 0)            AS gst_collected,
                COALESCE(SUM(CASE WHEN type='expense'
                    THEN gst_amount ELSE 0 END), 0)            AS gst_paid
            FROM ledger
        """).fetchone()
        d = dict(row)
        d["net_cashflow"] = round(d["total_income"] - d["total_expenses"], 2)
        d["net_gst_liability"] = round(d["gst_collected"] - d["gst_paid"], 2)
        return d


def ledger_get_all() -> list[dict]:
    """Return all ledger entries."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ledger ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GST summary operations
# ---------------------------------------------------------------------------

def gst_update(financial_data: dict) -> dict:
    """Update running GST totals atomically."""
    event_type = financial_data.get("event_type")
    has_invoice = bool(financial_data.get("invoice_id"))

    with get_conn() as conn:
        if event_type == "income":
            conn.execute("""
                UPDATE gst_summary SET
                    total_income        = total_income + ?,
                    total_gst_collected = total_gst_collected + ?,
                    invoice_count       = invoice_count + ?,
                    net_gst_liability   = total_gst_collected + ? - total_gst_paid,
                    last_updated        = datetime('now')
                WHERE id = 1
            """, (
                financial_data["total_amount"],
                financial_data["gst_amount"],
                1 if has_invoice else 0,
                financial_data["gst_amount"],
            ))
        elif event_type == "expense":
            conn.execute("""
                UPDATE gst_summary SET
                    total_expenses  = total_expenses + ?,
                    total_gst_paid  = total_gst_paid + ?,
                    net_gst_liability = total_gst_collected - (total_gst_paid + ?),
                    last_updated    = datetime('now')
                WHERE id = 1
            """, (
                financial_data["total_amount"],
                financial_data["gst_amount"],
                financial_data["gst_amount"],
            ))

        row = conn.execute("SELECT * FROM gst_summary WHERE id = 1").fetchone()
        return dict(row)


def gst_get() -> dict:
    """Return current GST summary."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM gst_summary WHERE id = 1").fetchone()
        return dict(row)


# ---------------------------------------------------------------------------
# Audit log operations
# ---------------------------------------------------------------------------

def audit_insert(verification: dict, extra: dict = None) -> dict:
    """Append an audit entry."""
    details = {**(verification.get("metadata") or {}), **(extra or {})}
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_log
                (timestamp, action, risk_level, status, decision_reason, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                verification.get("timestamp", datetime.now().isoformat()),
                verification.get("action", "unknown"),
                verification.get("risk_level", "medium"),
                "approved" if verification.get("approved") else "rejected",
                verification.get("decision_reason", "unknown"),
                json.dumps(details),
            ),
        )
        row = conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def audit_get_recent(n: int = 10) -> list[dict]:
    """Return last N audit entries."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Migration: import existing CSV / JSON data into DB
# ---------------------------------------------------------------------------

def migrate_from_files():
    """
    One-time migration: read existing flat files and insert into SQLite.
    Safe to call multiple times — skips if DB already has data.
    """
    import csv as csv_mod

    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        if count > 0:
            print(f"  [DB] Already has {count} ledger rows — skipping migration.")
            return

    data_dir = os.path.join(os.path.dirname(__file__), "../../data")
    ledger_csv = os.path.join(data_dir, "ledger.csv")
    gst_json = os.path.join(data_dir, "gst_summary.json")
    audit_jsonl = os.path.join(data_dir, "audit_log.jsonl")

    migrated = {"ledger": 0, "audit": 0}

    # Migrate ledger.csv
    if os.path.exists(ledger_csv):
        with open(ledger_csv, newline="") as f:
            for row in csv_mod.DictReader(f):
                with get_conn() as conn:
                    conn.execute("""
                        INSERT INTO ledger
                            (date, type, counterparty, description,
                             base_amount, gst_amount, total_amount,
                             status, invoice_id)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (
                        row.get("date", ""),
                        row.get("type", "expense"),
                        row.get("counterparty", "Unknown"),
                        row.get("description", ""),
                        float(row.get("base_amount", 0) or 0),
                        float(row.get("gst_amount", 0) or 0),
                        float(row.get("total_amount", 0) or 0),
                        row.get("status", "completed"),
                        row.get("invoice_id", ""),
                    ))
                migrated["ledger"] += 1

    # Migrate gst_summary.json
    if os.path.exists(gst_json):
        with open(gst_json) as f:
            g = json.load(f)
        with get_conn() as conn:
            conn.execute("""
                UPDATE gst_summary SET
                    total_income        = ?,
                    total_expenses      = ?,
                    total_gst_collected = ?,
                    total_gst_paid      = ?,
                    net_gst_liability   = ?,
                    invoice_count       = ?,
                    last_updated        = ?
                WHERE id = 1
            """, (
                g.get("total_income", 0),
                g.get("total_expenses", 0),
                g.get("total_gst_collected", 0),
                g.get("total_gst_paid", 0),
                g.get("net_gst_liability", 0),
                g.get("invoice_count", 0),
                g.get("last_updated"),
            ))

    # Migrate audit_log.jsonl
    if os.path.exists(audit_jsonl):
        with open(audit_jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    with get_conn() as conn:
                        conn.execute("""
                            INSERT INTO audit_log
                                (timestamp, action, risk_level, status,
                                 decision_reason, details)
                            VALUES (?,?,?,?,?,?)
                        """, (
                            entry.get("timestamp", ""),
                            entry.get("action", "unknown"),
                            entry.get("risk_level", "medium"),
                            entry.get("status", "approved"),
                            entry.get("decision_reason", ""),
                            json.dumps(entry.get("details", {})),
                        ))
                    migrated["audit"] += 1
                except (json.JSONDecodeError, Exception):
                    continue

    print(f"  [DB] Migration complete — ledger: {migrated['ledger']} rows, audit: {migrated['audit']} entries")


# ---------------------------------------------------------------------------
# Init on import
# ---------------------------------------------------------------------------

init_db()


if __name__ == "__main__":
    migrate_from_files()
    print("\nLedger summary:", ledger_get_summary())
    print("GST summary:", gst_get())
    print("Recent entries:", len(ledger_get_recent()))
    print("Pending invoices:", ledger_get_pending())
    print("Recent audit:", len(audit_get_recent()))
