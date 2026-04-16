"""
trust.py — Verification Layer
Controls execution of sensitive actions with risk assessment and approval logging.
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")
AUDIT_LOG_PATH = os.path.join(DATA_DIR, "audit_log.jsonl")

# Risk classification rules
RISK_RULES = {
    "generate_invoice": {
        "risk_level": "low",
        "reason": "Local file generation only",
        "requires_approval": False,
    },
    "update_ledger": {
        "risk_level": "low",
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
    """Append a decision to the audit log."""
    os.makedirs(DATA_DIR, exist_ok=True)
    entry = {
        "timestamp": verification.get("timestamp", datetime.now().isoformat()),
        "action": verification.get("action"),
        "risk_level": verification.get("risk_level"),
        "status": "approved" if verification.get("approved") else "rejected",
        "decision_reason": verification.get("decision_reason", "unknown"),
        "details": {
            **(verification.get("metadata") or {}),
            **(extra or {}),
        },
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


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
    """Return last N audit log entries."""
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    entries = []
    with open(AUDIT_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries[-n:]


if __name__ == "__main__":
    v = assess_action("send_invoice", metadata={"invoice_id": "INV-2026-0001", "client": "ABC Corp"})
    print(json.dumps(v, indent=2))
    v = request_approval(v, auto_approve=True)
    print(json.dumps(v, indent=2))
    entry = log_decision(v)
    print("Logged:", json.dumps(entry, indent=2))
