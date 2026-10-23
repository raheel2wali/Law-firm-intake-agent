"""The hands: the three things LexIntake is allowed to DO.

Read freely, write carefully. Everything in this module can read without
asking, but nothing writes to a real system on its own. A write is always
proposed first: it lands in a pending queue with a token, and it only
executes when someone approves it through POST /confirm (see app/main.py).

Dry-run mode (DRY_RUN=1) points the tools at in-memory stub adapters so
the whole pipeline can be tested without touching real systems. With it
off, the adapters come from app/integrations.py (Part 9): Google Calendar,
a Clio-style case management API, and Twilio/SMTP messaging, picked per
system through the LEXINTAKE_* environment variables. Until the real
credentials are set, those adapters raise IntegrationNotWired instead of
silently pretending.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import integrations
from app.integrations import IntegrationNotWired  # re-exported; main.py imports it from here

# ---------------------------------------------------------------------------
# Scopes: each tool declares what it needs, the deployment grants what the
# agent may hold. Narrow this down in production (e.g. read-only followers
# get no write scopes at all). Reads never need a scope.
# ---------------------------------------------------------------------------

TOOL_SCOPES = {
    "book_consultation": "write:calendar",
    "create_matter": "write:matters",
    "send_followup": "write:followups",
}

GRANTED_SCOPES = set(
    os.environ.get(
        "LEXINTAKE_SCOPES", "write:calendar,write:matters,write:followups"
    ).split(",")
)

DRY_RUN = os.environ.get("DRY_RUN", "1").lower() in ("1", "true", "yes")

AUDIT_LOG = Path(__file__).resolve().parent.parent / "data" / "audit.log.jsonl"

PENDING_TTL = timedelta(minutes=15)
_pending: dict[str, dict] = {}  # token -> pending action


class ScopeDenied(PermissionError):
    """The agent tried to use a tool outside its granted scopes."""


def require_scope(tool_name: str) -> None:
    scope = TOOL_SCOPES[tool_name]
    if scope not in GRANTED_SCOPES:
        raise ScopeDenied(f"tool {tool_name} needs scope {scope!r}, not granted")


# ---------------------------------------------------------------------------
# Adapters: where writes actually go. The stub adapters (in-memory, no
# network) run in dry-run mode for testing. Otherwise the factories in
# app/integrations.py pick the real adapters from the environment, and
# they are constructed lazily, on first use, so missing credentials fail
# loudly at execution time rather than at import time.
# ---------------------------------------------------------------------------


def _calendar():
    if DRY_RUN:
        return _stubs.setdefault("calendar", integrations.StubCalendar())
    return integrations.make_calendar()


def _matters():
    if DRY_RUN:
        return _stubs.setdefault("matters", integrations.StubMatters())
    return integrations.make_case_management()


def _followups():
    if DRY_RUN:
        return _stubs.setdefault("followups", integrations.StubMessaging())
    return integrations.make_messaging()


_stubs: dict[str, object] = {}  # dry-run only: shared stub state across calls


# ---------------------------------------------------------------------------
# Audit trail: every proposal, approval, decline, and execution is a line
# a partner can skim in 30 seconds.
# ---------------------------------------------------------------------------


def _audit(event: str, action: dict, extra: dict | None = None) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "tool": action["tool"],
        "token": action["token"],
        "dry_run": DRY_RUN,
        "args": action["args"],
    }
    if extra:
        record.update(extra)
    with AUDIT_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# The pending queue: propose first, execute only on approval.
# ---------------------------------------------------------------------------


def _propose(tool_name: str, args: dict) -> dict:
    token = secrets.token_urlsafe(16)
    action = {
        "tool": tool_name,
        "token": token,
        "args": args,
        "status": "pending",
        "expires_at": (datetime.now(timezone.utc) + PENDING_TTL).isoformat(),
    }
    _pending[token] = action
    _audit("proposed", action)
    return {
        "status": "pending_confirmation",
        "tool": tool_name,
        "token": token,
        "summary": f"{tool_name} proposed; approve with POST /confirm {{token, approved}}",
    }


def list_pending() -> list[dict]:
    now = datetime.now(timezone.utc)
    live = []
    for token, action in list(_pending.items()):
        if datetime.fromisoformat(action["expires_at"]) < now:
            action["status"] = "expired"
            _audit("expired", action)
            del _pending[token]
            continue
        live.append(
            {"tool": action["tool"], "token": token, "args": action["args"]}
        )
    return live


def confirm_action(token: str, *, approved: bool, note: str = "") -> dict:
    action = _pending.get(token)
    if action is None:
        raise KeyError("unknown or expired token")
    del _pending[token]
    if not approved:
        action["status"] = "declined"
        _audit("declined", action, {"note": note})
        return {"status": "declined", "tool": action["tool"]}
    try:
        result = _execute(action)
    except IntegrationNotWired as exc:
        action["status"] = "blocked"
        _audit("blocked", action, {"error": str(exc)})
        raise
    action["status"] = "executed"
    _audit("executed", action, {"result": result})
    return {"status": "executed", "tool": action["tool"], "result": result}


def _execute(action: dict) -> dict:
    tool, args = action["tool"], action["args"]
    if tool == "book_consultation":
        return _calendar().book(**args)
    if tool == "create_matter":
        return _matters().create(summary=args["intake_summary"])
    if tool == "send_followup":
        return _followups().send(**args)
    raise ValueError(f"unknown tool {tool}")


# ---------------------------------------------------------------------------
# The three tools.
# ---------------------------------------------------------------------------


def book_consultation(intake_summary: str, slot: str, contact: str) -> dict:
    """Propose a consultation booking. The slot is checked first (a read,
    free of charge); the write itself needs confirmation."""
    require_scope("book_consultation")
    if not _calendar().slot_free(slot):
        return {"status": "slot_taken", "slot": slot}
    return _propose(
        "book_consultation",
        {"intake_summary": intake_summary, "slot": slot, "contact": contact},
    )


def create_matter(intake_summary: str) -> dict:
    """Propose opening a matter with the intake card attached."""
    require_scope("create_matter")
    return _propose("create_matter", {"intake_summary": intake_summary})


def send_followup(booking_ref: str, channel: str, message: str) -> dict:
    """Propose a confirmation/reminder/reschedule follow-up by text or email."""
    require_scope("send_followup")
    if channel not in ("sms", "email"):
        raise ValueError("channel must be 'sms' or 'email'")
    return _propose(
        "send_followup",
        {"booking_ref": booking_ref, "channel": channel, "message": message},
    )


def run_booking(intake_summary: str, slot: str, contact: str) -> dict:
    """What the agent does once run_turn() says 'book': propose the three
    writes in order. Each comes back pending until a human confirms."""
    return {
        "consultation": book_consultation(intake_summary, slot, contact),
        "matter": create_matter(intake_summary),
        # The follow-up is proposed against the booking only after the
        # booking itself is confirmed and returns a real ref; for now the
        # caller proposes it with the ref from confirm_action's result.
        "followup": {"status": "awaiting_booking_confirmation"},
    }
