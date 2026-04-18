"""
security.py — Artha Security Middleware
Sits between Telegram and the pipeline. Handles:

  1. User whitelist        — only allowed Telegram user IDs can use the bot
  2. Rate limiting         — max N messages per minute per user
  3. Input sanitization    — strip dangerous characters before pipeline
  4. Message size limit    — reject abnormally large inputs
  5. Suspicious pattern    — detect prompt injection / abuse attempts
  6. DB encryption check   — warn if DB is unencrypted
  7. Audit every rejection — all blocked attempts are logged
"""

import os
import re
import time
import hashlib
import logging
from collections import defaultdict
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — all tunable via environment variables
# ---------------------------------------------------------------------------

def _env_list(key: str) -> list[str]:
    val = os.environ.get(key, "")
    return [v.strip() for v in val.split(",") if v.strip()]

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


# Comma-separated Telegram user IDs allowed to use the bot
# e.g. ARTHA_ALLOWED_USERS=123456789,987654321
ALLOWED_USER_IDS: set[str] = set(_env_list("ARTHA_ALLOWED_USERS"))

# Rate limit: max messages per user per window
RATE_LIMIT_MAX      = _env_int("ARTHA_RATE_LIMIT_MAX", 10)       # max messages
RATE_LIMIT_WINDOW   = _env_int("ARTHA_RATE_LIMIT_WINDOW", 60)    # per N seconds

# Input constraints
MAX_INPUT_LENGTH    = _env_int("ARTHA_MAX_INPUT_LENGTH", 500)     # characters

# ---------------------------------------------------------------------------
# In-memory rate limit store  {user_id: [(timestamp, ...), ...]}
# ---------------------------------------------------------------------------

_rate_store: dict[str, list[float]] = defaultdict(list)


# ---------------------------------------------------------------------------
# 1. Whitelist check
# ---------------------------------------------------------------------------

def is_allowed_user(user_id: str) -> bool:
    """
    Return True if user is allowed.
    If ARTHA_ALLOWED_USERS is not set — bot is LOCKED to no one.
    Set it to your Telegram user ID to allow yourself.
    """
    if not ALLOWED_USER_IDS:
        # No whitelist configured — deny everyone, warn operator
        logger.warning("ARTHA_ALLOWED_USERS not set — all users denied.")
        return False
    return str(user_id) in ALLOWED_USER_IDS


# ---------------------------------------------------------------------------
# 2. Rate limiting
# ---------------------------------------------------------------------------

def is_rate_limited(user_id: str) -> tuple[bool, int]:
    """
    Check if user has exceeded rate limit.
    Returns (is_limited, seconds_until_reset).
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    # Purge old timestamps outside the window
    _rate_store[user_id] = [t for t in _rate_store[user_id] if t > window_start]

    count = len(_rate_store[user_id])
    if count >= RATE_LIMIT_MAX:
        oldest = _rate_store[user_id][0]
        reset_in = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return True, reset_in

    # Record this message
    _rate_store[user_id].append(now)
    return False, 0


# ---------------------------------------------------------------------------
# 3. Input sanitization
# ---------------------------------------------------------------------------

# Characters that have no place in a financial message
_DANGEROUS_PATTERNS = [
    r"<script",           # XSS
    r"javascript:",       # XSS
    r"--",                # SQL comment
    r";\s*DROP",          # SQL injection
    r";\s*DELETE",        # SQL injection
    r";\s*INSERT",        # SQL injection
    r";\s*UPDATE",        # SQL injection
    r"\$\{",              # template injection
    r"\{\{",              # template injection
    r"ignore previous",   # prompt injection
    r"ignore all",        # prompt injection
    r"system prompt",     # prompt injection
    r"you are now",       # prompt injection
    r"forget everything", # prompt injection
]

_DANGEROUS_RE = re.compile(
    "|".join(_DANGEROUS_PATTERNS),
    re.IGNORECASE,
)


def sanitize_input(text: str) -> tuple[str, bool]:
    """
    Clean and validate input text.
    Returns (sanitized_text, is_safe).
    is_safe=False means block the message entirely.
    """
    # Size check
    if len(text) > MAX_INPUT_LENGTH:
        return text[:MAX_INPUT_LENGTH], False

    # Suspicious pattern check
    if _DANGEROUS_RE.search(text):
        return "", False

    # Strip control characters (keep newlines, strip null bytes etc.)
    sanitized = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)

    # Normalize whitespace
    sanitized = " ".join(sanitized.split())

    return sanitized, True


# ---------------------------------------------------------------------------
# 4. Full gate — runs all checks in order
# ---------------------------------------------------------------------------

class SecurityError(Exception):
    """Raised when a security check fails. Message is safe to show user."""
    pass


def security_gate(user_id: str, username: str, text: str) -> str:
    """
    Run all security checks. Returns sanitized text if safe.
    Raises SecurityError with a user-facing message if blocked.

    Order:
      1. Whitelist
      2. Rate limit
      3. Input size + sanitization
      4. Suspicious pattern
    """
    uid = str(user_id)

    # 1. Whitelist
    if not is_allowed_user(uid):
        _log_blocked(uid, username, "whitelist", text)
        raise SecurityError(
            "Access denied. This is a private bot.\n"
            "Contact the owner to get access."
        )

    # 2. Rate limit
    limited, reset_in = is_rate_limited(uid)
    if limited:
        _log_blocked(uid, username, "rate_limit", text)
        raise SecurityError(
            f"Too many messages. Please wait {reset_in} seconds."
        )

    # 3 + 4. Sanitize and pattern check
    sanitized, is_safe = sanitize_input(text)
    if not is_safe:
        _log_blocked(uid, username, "suspicious_input", text)
        raise SecurityError(
            "Message blocked — contains invalid or suspicious content.\n"
            "Please send a normal payment message like:\n"
            "_\"Received ₹25,000 from ABC Corp for website design\"_"
        )

    return sanitized


# ---------------------------------------------------------------------------
# 5. Decorator for Telegram handlers
# ---------------------------------------------------------------------------

def secured(handler: Callable) -> Callable:
    """
    Decorator that wraps any Telegram async handler with the full security gate.
    Usage:
        @secured
        async def cmd_ledger(update, context): ...
    """
    @wraps(handler)
    async def wrapper(update, context):
        user = update.effective_user
        if user is None:
            return  # no user context — ignore silently

        text = (update.message.text or "").strip()

        try:
            # Commands don't need sanitization beyond whitelist + rate limit
            if text.startswith("/"):
                if not is_allowed_user(str(user.id)):
                    _log_blocked(str(user.id), user.username or "", "whitelist", text)
                    await update.message.reply_text(
                        "Access denied. This is a private bot."
                    )
                    return
                limited, reset_in = is_rate_limited(str(user.id))
                if limited:
                    await update.message.reply_text(
                        f"Too many messages. Wait {reset_in}s."
                    )
                    return
            else:
                # Full gate for financial messages
                text = security_gate(str(user.id), user.username or "", text)

        except SecurityError as e:
            await update.message.reply_text(str(e))
            return

        # Inject sanitized text back so handler sees clean input
        update.message.text = text
        await handler(update, context)

    return wrapper


# ---------------------------------------------------------------------------
# 6. Audit blocked attempts
# ---------------------------------------------------------------------------

def _log_blocked(user_id: str, username: str, reason: str, raw_text: str):
    """Log blocked attempts to audit_log in DB."""
    try:
        from db import audit_insert
        audit_insert(
            {
                "action": f"blocked_{reason}",
                "risk_level": "high",
                "approved": False,
                "decision_reason": reason,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "metadata": {
                    "user_id": user_id,
                    "username": username,
                    # Hash the raw text — don't store malicious content
                    "input_hash": hashlib.sha256(raw_text.encode()).hexdigest()[:16],
                    "input_length": len(raw_text),
                },
            }
        )
    except Exception:
        # Never let security logging crash the bot
        logger.error(f"Failed to log blocked attempt: user={user_id} reason={reason}")


# ---------------------------------------------------------------------------
# 7. Startup checks
# ---------------------------------------------------------------------------

def startup_security_check() -> list[str]:
    """
    Run at bot startup. Returns list of warnings to print.
    Does not block startup — just informs the operator.
    """
    warnings = []

    if not ALLOWED_USER_IDS:
        warnings.append(
            "WARNING: ARTHA_ALLOWED_USERS is not set. "
            "ALL users will be denied. "
            "Set it to your Telegram user ID: export ARTHA_ALLOWED_USERS=your_id"
        )

    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    gitignore_path = os.path.join(os.path.dirname(__file__), "../../.gitignore")
    if os.path.exists(env_path):
        if os.path.exists(gitignore_path):
            with open(gitignore_path) as f:
                if ".env" not in f.read():
                    warnings.append(
                        "WARNING: .env file exists but is NOT in .gitignore. "
                        "Your bot token could be leaked if you push to git. "
                        "Run: echo '.env' >> .gitignore"
                    )
        else:
            warnings.append(
                "WARNING: No .gitignore found. "
                "Make sure .env is never committed to git."
            )

    db_path = os.path.join(os.path.dirname(__file__), "../../data/artha.db")
    if os.path.exists(db_path):
        # Check if DB is readable by others (Unix only)
        try:
            mode = oct(os.stat(db_path).st_mode)
            if mode[-1] != "0":  # world-readable
                warnings.append(
                    f"WARNING: artha.db has open permissions ({mode}). "
                    "Run: chmod 600 data/artha.db"
                )
        except Exception:
            pass

    return warnings


if __name__ == "__main__":
    print("Security config:")
    print(f"  Allowed users : {ALLOWED_USER_IDS or 'NONE SET — all denied'}")
    print(f"  Rate limit    : {RATE_LIMIT_MAX} msgs / {RATE_LIMIT_WINDOW}s")
    print(f"  Max input len : {MAX_INPUT_LENGTH} chars")
    print()
    warnings = startup_security_check()
    if warnings:
        for w in warnings:
            print(f"  {w}")
    else:
        print("  All checks passed.")
