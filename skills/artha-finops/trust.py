"""
trust.py — Verification Layer
Controls execution of sensitive actions with risk assessment and approval logging.
"""

import json
import os
from datetime import datetime

from db import audit_insert, audit_get_recent as db_audit_get_recent

# Risk classification rules
RISK_RULES = {
    "verify_payment": {
        "risk_level": "high",
        "reason": "Payment amount must be confirmed before invoice is issued",
        "requires_approval": True,
    },
    "generate_invoice": {
        "risk_level": "high",
        "reason": "Invoice is a legal financial document — payment must be verified first",
        "requires_approval": True,
    },
    "update_ledger": {
        "risk_level": "medium",
        "reason": "Local data modification",
        "requires_approval": False,
    },
    "send_invoice": {
        "risk_level": "high",
        "reason": "External communication to client",
        "requires_approval": True,
    },
    "update_gst_summary": {
        "risk_level": "medium",
        "reason": "Modifies compliance-relevant financial state",
        "requires_approval": False,
    },
    "modify_ledger_entry": {
        "risk_level": "high",
        "reason": "Retroactive financial record change",
        "requires_approval": True,
    },
    "external_api_call": {
        "risk_level": "high",
        "reason": "External system interaction",
        "requires_approval": True,
    },
}


def assess_action(action: str, metadata: dict = None) -> dict:
    """
    Assess an action and return a verification context.

    Returns:
        {
            action, risk_level, reason, requires_approval,
            metadata, timestamp
        }
    """
    rule = RISK_RULES.get(action, {
        "risk_level": "medium",
        "reason": "Unknown action type",
        "requires_approval": True,
    })
    return {
        "action": action,
        "risk_level": rule["risk_level"],
        "reason": rule["reason"],
        "requires_approval": rule["requires_approval"],
        "metadata": metadata or {},
        "timestamp": datetime.now().isoformat(),
    }


def request_approval(verification: dict, auto_approve: bool = False) -> dict:
    """
    Request approval for a sensitive action.

    In demo mode (auto_approve=True), automatically approves.
    In interactive mode, prompts the user.

    Returns:
        Updated verification dict with "approved" and "decision_reason" fields.
    """
    v = verification.copy()

    if not v["requires_approval"] or auto_approve:
        v["approved"] = True
        v["decision_reason"] = "auto-approved" if not v["requires_approval"] else "demo-mode"
        return v

    # Interactive prompt
    print("\n" + "=" * 60)
    print("  VERIFICATION REQUIRED")
    print("=" * 60)
    print(f"  Action      : {v['action']}")
    print(f"  Risk Level  : {v['risk_level'].upper()}")
    print(f"  Reason      : {v['reason']}")
    if v["metadata"]:
        for key, val in v["metadata"].items():
            print(f"  {key.title():<12}: {val}")
    print("=" * 60)

    while True:
        choice = input("  Approve? [y/n]: ").strip().lower()
        if choice in ("y", "yes"):
            v["approved"] = True
            v["decision_reason"] = "user-approved"
            break
        elif choice in ("n", "no"):
            v["approved"] = False
            v["decision_reason"] = "user-rejected"
            break
        else:
            print("  Please enter y or n.")

    return v


def log_decision(verification: dict, extra: dict = None):
    """Append a decision to the audit log in DB."""
    return audit_insert(verification, extra=extra)


def verify_payment_amount(
    parsed_amount: float,
    expected_amount: float,
    tolerance: float = 0.01,
) -> dict:
    """
    Check whether the payment amount in the message matches the expected amount.

    Args:
        parsed_amount:   Amount extracted from the user's message.
        expected_amount: Amount that was actually expected (e.g. from a prior invoice).
                         Pass the same as parsed_amount when there is no prior invoice
                         — in that case the check is a confirmation, not a mismatch check.
        tolerance:       Fractional tolerance (default 1%) to allow minor rounding.

    Returns:
        {
            "verified": bool,
            "parsed_amount": float,
            "expected_amount": float,
            "discrepancy": float,
            "reason": str,
        }
    """
    discrepancy = abs(parsed_amount - expected_amount)
    allowed_delta = expected_amount * tolerance

    if discrepancy <= allowed_delta:
        return {
            "verified": True,
            "parsed_amount": parsed_amount,
            "expected_amount": expected_amount,
            "discrepancy": round(discrepancy, 2),
            "reason": "Amount matches expected value within tolerance.",
        }
    else:
        return {
            "verified": False,
            "parsed_amount": parsed_amount,
            "expected_amount": expected_amount,
            "discrepancy": round(discrepancy, 2),
            "reason": (
                f"Amount mismatch: received ₹{parsed_amount:,.2f} "
                f"but expected ₹{expected_amount:,.2f} "
                f"(difference ₹{discrepancy:,.2f})."
            ),
        }


def execute_with_verification(
    action: str,
    fn,
    metadata: dict = None,
    auto_approve: bool = False,
):
    """
    Wraps any callable with the full verification flow:
    assess → request approval → execute (if approved) → log.

    Args:
        action: Action name (must match RISK_RULES keys)
        fn: Callable to execute if approved
        metadata: Context to show in the approval prompt
        auto_approve: Skip interactive prompt (for demo/testing)

    Returns:
        {
            "approved": bool,
            "result": fn() output or None,
            "audit_entry": logged entry
        }
    """
    verification = assess_action(action, metadata)
    verification = request_approval(verification, auto_approve=auto_approve)
    result = None

    if verification["approved"]:
        result = fn()

    audit_entry = log_decision(verification, extra={"executed": verification["approved"]})

    return {
        "approved": verification["approved"],
        "result": result,
        "audit_entry": audit_entry,
    }


def get_audit_log(n: int = 10) -> list[dict]:
    """Return last N audit log entries from DB."""
    return db_audit_get_recent(n)


if __name__ == "__main__":
    v = assess_action("send_invoice", metadata={"invoice_id": "INV-2026-0001", "client": "ABC Corp"})
    print(json.dumps(v, indent=2))
    v = request_approval(v, auto_approve=True)
    print(json.dumps(v, indent=2))
    entry = log_decision(v)
    print("Logged:", json.dumps(entry, indent=2))
