"""Audit log. Secrets are redacted and long values are cut before anything is stored."""
import json
import re

from db import db, new_id, utcnow

SENSITIVE_KEY = re.compile(r"(password|passwd|token|secret|api[_-]?key|card|cvv|authorization|iban)", re.I)
MAX_LEN = 300


def redact(value, depth=0):
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if SENSITIVE_KEY.search(str(k)) else redact(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value[:10]]
    return value


def summarize(value) -> str:
    if value is None:
        return ""
    text = json.dumps(redact(value), default=str)
    return text if len(text) <= MAX_LEN else text[:MAX_LEN] + "...[cut]"


def log(case_id, tool, action, input=None, output=None, actor="ai-agent",
        approval_status=None, execution_status=None, error=None):
    entry = {
        "audit_id": new_id("AUD"),
        "ts": utcnow(),
        "case_id": case_id,
        "actor": actor,
        "tool": tool,
        "action": action,
        "input_summary": summarize(input),
        "output_summary": summarize(output),
        "approval_status": approval_status,
        "execution_status": execution_status,
        "error": (str(error)[:200] if error else None),
    }
    db.audit_logs.insert_one(dict(entry))
    return entry
