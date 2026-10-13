"""Append-only JSON audit trail for agent coordination."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .limits import MAX_AUDIT_TEXT_LENGTH


AUDIT_PATH = Path(__file__).resolve().parents[1] / "output" / "audit_trail.json"


def _short(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if any(secret in lowered for secret in ("api_key", "password", "authorization", "bearer ")):
            return "[REDACTED]"
        return value if len(value) <= MAX_AUDIT_TEXT_LENGTH else value[:MAX_AUDIT_TEXT_LENGTH] + "..."
    if isinstance(value, dict):
        return {str(key): _short(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_short(item) for item in value[:20]]
    return value


def append_audit_entry(
    *,
    ticket_id: int,
    agent_name: str,
    action: str,
    arguments: Any = None,
    result: Any = None,
    iteration: int = 0,
    delegation_depth: int = 0,
    approval_required: bool = False,
    status: str = "in_progress",
    stop_reason: str | None = None,
) -> dict[str, Any]:
    """Append one bounded, redacted entry without removing prior entries."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticket_id": ticket_id,
        "agent_name": agent_name,
        "action": action,
        "arguments": _short(arguments),
        "result": _short(result),
        "iteration": iteration,
        "delegation_depth": delegation_depth,
        "approval_required": approval_required,
        "status": status,
        "stop_reason": stop_reason,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if AUDIT_PATH.exists():
        existing = json.loads(AUDIT_PATH.read_text())
        if not isinstance(existing, list):
            raise ValueError("audit_trail.json must contain a JSON array")
    else:
        existing = []
    existing.append(entry)
    AUDIT_PATH.write_text(json.dumps(existing, indent=2) + "\n")
    return entry
