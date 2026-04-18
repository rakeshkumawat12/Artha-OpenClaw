# Artha FinOps — Security Architecture

Artha uses a layered, custom-built security model with no external security dependencies. Every message from Telegram passes through multiple gates before reaching the AI pipeline or database.

---

## 1. Overall Request Flow

```mermaid
flowchart TD
    U([Telegram User]) --> TG[Telegram API]
    TG --> SEC{{"@secured decorator\nsecurity.py"}}

    SEC -->|command /start /ledger etc| WL[Whitelist Check]
    SEC -->|free-text message| GATE[security_gate]

    GATE --> WL
    WL -->|denied| BLOCK1[Block + Audit Log]
    WL -->|allowed| RL[Rate Limit Check]

    RL -->|exceeded| BLOCK2[Block + Audit Log]
    RL -->|ok| SAN[Input Sanitization\n+ Pattern Check]

    SAN -->|dangerous| BLOCK3[Block + Audit Log]
    SAN -->|clean| PIPE[AI Pipeline\nparser → finance → trust]

    PIPE --> DB[(SQLite\nartha.db)]
    PIPE --> OUT[Formatted Response]
    OUT --> U

    BLOCK1 & BLOCK2 & BLOCK3 --> AUDIT[(audit_log\ntable)]

    style BLOCK1 fill:#c0392b,color:#fff
    style BLOCK2 fill:#c0392b,color:#fff
    style BLOCK3 fill:#c0392b,color:#fff
    style AUDIT fill:#8e44ad,color:#fff
    style DB fill:#2980b9,color:#fff
```

---

## 2. Security Middleware Layers

```mermaid
flowchart LR
    subgraph security.py ["security.py — 4-Layer Gate"]
        direction TB
        L1["1. Whitelist\nARTHA_ALLOWED_USERS\nenv var"]
        L2["2. Rate Limit\n10 msg / 60s\nper user"]
        L3["3. Size Check\nmax 500 chars"]
        L4["4. Pattern Scan\nXSS · SQLi · Template\nPrompt Injection"]
        L1 --> L2 --> L3 --> L4
    end

    IN([Raw Input]) --> L1
    L4 --> OUT([Sanitized Text])

    style L1 fill:#1a5276,color:#fff
    style L2 fill:#1a5276,color:#fff
    style L3 fill:#1a5276,color:#fff
    style L4 fill:#1a5276,color:#fff
```

### Blocked patterns (`security.py:106-121`)

| Category | Patterns detected |
|---|---|
| XSS | `<script`, `javascript:` |
| SQL injection | `--`, `; DROP`, `; DELETE`, `; INSERT`, `; UPDATE` |
| Template injection | `${`, `{{` |
| Prompt injection | `ignore previous`, `ignore all`, `system prompt`, `you are now`, `forget everything` |

---

## 3. Trust & Action Verification Layer

High-risk financial actions require explicit verification before execution. This is handled by `trust.py`.

```mermaid
flowchart TD
    ACTION([Action requested]) --> ASSESS[assess_action\nLook up RISK_RULES]

    ASSESS --> HIGH{"risk_level?"}

    HIGH -->|high + requires_approval=true| PROMPT[Request Approval\nInteractive or auto_approve]
    HIGH -->|medium + requires_approval=false| AUTO[Auto-approved]

    PROMPT -->|user approves| EXEC[Execute fn]
    PROMPT -->|user rejects| SKIP[Skip execution]
    AUTO --> EXEC

    EXEC --> LOG[log_decision\n→ audit_log DB]
    SKIP --> LOG

    style HIGH fill:#d35400,color:#fff
    style LOG fill:#8e44ad,color:#fff
```

### Risk classification (`trust.py:13-49`)

| Action | Risk Level | Requires Approval |
|---|---|---|
| `verify_payment` | high | yes |
| `generate_invoice` | high | yes |
| `send_invoice` | high | yes |
| `modify_ledger_entry` | high | yes |
| `external_api_call` | high | yes |
| `update_ledger` | medium | no |
| `update_gst_summary` | medium | no |
| unknown action | medium | yes (fail-safe) |

---

## 4. Payment Verification Flow

Income events are verified against open invoices before the ledger is updated.

```mermaid
flowchart TD
    MSG([Income message]) --> PARSE[Parse amount + counterparty]
    PARSE --> OPEN{Open invoice\nfor counterparty?}

    OPEN -->|yes| MATCH[verify_payment_amount\ntolerance ±1%]
    OPEN -->|no| SELFVERIFY[Self-verify\nparsed == expected]

    MATCH -->|within tolerance| COMPLETE[Mark invoice COMPLETED\nUpdate ledger]
    MATCH -->|mismatch| ALERT[Send mismatch alert\nBlock ledger update\nLog to audit_log]

    SELFVERIFY --> COMPLETE

    COMPLETE --> GST[Update GST summary]

    style ALERT fill:#c0392b,color:#fff
    style COMPLETE fill:#1e8449,color:#fff
```

---

## 5. Audit Log

Every blocked request and every sensitive action decision is written to the `audit_log` table in SQLite. Raw malicious content is never stored — only a SHA-256 hash prefix.

```mermaid
erDiagram
    audit_log {
        INTEGER id PK
        TEXT timestamp
        TEXT action
        TEXT risk_level
        TEXT status
        TEXT decision_reason
        TEXT details
    }

    audit_log ||--o{ blocked_whitelist : "reason=blocked_whitelist"
    audit_log ||--o{ blocked_rate_limit : "reason=blocked_rate_limit"
    audit_log ||--o{ blocked_suspicious_input : "reason=blocked_suspicious_input"
    audit_log ||--o{ verify_payment : "action=verify_payment"
    audit_log ||--o{ generate_invoice : "action=generate_invoice"
    audit_log ||--o{ send_invoice : "action=send_invoice"
```

Blocked attempts store:
- `user_id` + `username`
- `input_hash` — first 16 hex chars of `SHA-256(raw_input)` — never the raw content
- `input_length`
- block `reason`

---

## 6. Database Security

```mermaid
flowchart LR
    subgraph DB ["SQLite — artha.db"]
        direction TB
        WAL["WAL journal mode\nsafe concurrent reads+writes"]
        FK["Foreign key enforcement\nPRAGMA foreign_keys=ON"]
        TXN["Auto rollback on error\ncontextmanager get_conn"]
        PERM["File permissions\nchmod 600 (operator responsibility)"]
    end

    APP[Application] --> DB
    DB --> STARTUP[Startup check warns\nif world-readable]

    style WAL fill:#1a5276,color:#fff
    style FK fill:#1a5276,color:#fff
    style TXN fill:#1a5276,color:#fff
    style PERM fill:#d35400,color:#fff
```

Startup checks (`security.py:285-329`) warn the operator if:
- `ARTHA_ALLOWED_USERS` is not set (deny-all default)
- `.env` exists but is not in `.gitignore`
- `artha.db` has world-readable permissions

---

## 7. Secrets & Config

```mermaid
flowchart TD
    ENV[".env file\nTELEGRAM_BOT_TOKEN\nARTHA_ALLOWED_USERS"] -->|loaded at startup| BOT[telegram_bot.py]

    ENV -->|should never be| GIT[git repository]
    GIT -.->|startup warns if missing| GITIGNORE[".gitignore entry"]

    BOT --> SEC_CHECK[startup_security_check]
    SEC_CHECK -->|warns| OPERATOR([Operator console])

    style GIT fill:#c0392b,color:#fff
    style ENV fill:#1e8449,color:#fff
```

All tuneable security parameters are environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ARTHA_ALLOWED_USERS` | (none — deny all) | Comma-separated allowed Telegram user IDs |
| `ARTHA_RATE_LIMIT_MAX` | `10` | Max messages per window |
| `ARTHA_RATE_LIMIT_WINDOW` | `60` | Window size in seconds |
| `ARTHA_MAX_INPUT_LENGTH` | `500` | Max input characters |
| `TELEGRAM_BOT_TOKEN` | (required) | Bot authentication token |

---

## 8. Security Component Map

```mermaid
graph TD
    subgraph Entry ["Entry Point"]
        TG[Telegram API]
    end

    subgraph Middleware ["Security Middleware — security.py"]
        DEC["@secured decorator"]
        WL["is_allowed_user()"]
        RL["is_rate_limited()"]
        SAN["sanitize_input()"]
        GATE["security_gate()"]
        AUDIT_BLOCK["_log_blocked() → audit_log"]
    end

    subgraph Trust ["Trust Layer — trust.py"]
        ASSESS["assess_action()"]
        APPROVAL["request_approval()"]
        LOG_DEC["log_decision() → audit_log"]
        VERIFY["verify_payment_amount()"]
    end

    subgraph Data ["Data Layer — db.py"]
        LEDGER["ledger table"]
        GST["gst_summary table"]
        AUDIT_DB["audit_log table"]
    end

    TG --> DEC
    DEC --> WL --> RL --> SAN
    SAN --> GATE
    GATE -->|blocked| AUDIT_BLOCK --> AUDIT_DB
    GATE -->|clean| ASSESS
    ASSESS --> APPROVAL --> LOG_DEC --> AUDIT_DB
    APPROVAL --> VERIFY
    VERIFY --> LEDGER
    VERIFY --> GST

    style AUDIT_BLOCK fill:#c0392b,color:#fff
    style AUDIT_DB fill:#8e44ad,color:#fff
    style LEDGER fill:#2980b9,color:#fff
    style GST fill:#2980b9,color:#fff
```
