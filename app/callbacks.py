"""Bonus Part 1: The Callback.

A missed call's text-back is only half the job. What happens AFTER the
answer is where a firm proves itself: staff pick up the phone an hour
later, cold, with no name, no case type, and no urgency signal — and
the caller has to retell their story.

So every missed call now opens a Callback Card: the caller's phone
number, name, case type, and first-sentence urgency signal, already
filled in, with a 2-minute SLA timer running on it. Staff work the
queue top-down; the card tells them exactly who to call and why it
can't wait. A missed call is no longer a voicemail. It's a
ready-to-call card.

Cards live in data/callbacks.jsonl (one line per event) and in memory
while the server runs. Nothing here dials a phone — the call itself
stays with the firm's staff or telephony provider, same as Part 7.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

CALLBACK_LOG = Path(__file__).resolve().parent.parent / "data" / "callbacks.jsonl"

# The promise from the bonus post: a callback goes out in two minutes.
SLA_MINUTES = 2

_cards: dict[str, dict] = {}  # card id -> card


def _log(event: str, card: dict) -> None:
    CALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "event": event}
    record.update(card)
    with CALLBACK_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def create_callback_card(phone: str, name: str = "", case_type: str = "",
                         urgency_signal: str = "", call_id: str = "") -> dict:
    """Open a callback card. At missed-call time only the phone number
    is known; name, case type, and the urgency signal fill in when the
    caller replies and the interview runs (see update_callback_card)."""
    now = datetime.now(timezone.utc)
    card = {
        "id": secrets.token_urlsafe(12),
        "call_id": call_id,
        "phone": phone,
        "name": name,
        "case_type": case_type,
        "urgency_signal": urgency_signal,
        "status": "open",
        "created_at": now.isoformat(),
        "due_at": (now + timedelta(minutes=SLA_MINUTES)).isoformat(),
    }
    _cards[card["id"]] = card
    _log("created", card)
    return card


def update_callback_card(card_id: str, **fields: str) -> dict:
    """Fill in what the interview learned: name, case_type, or the
    first-sentence urgency signal. Unknown cards raise KeyError."""
    card = _cards.get(card_id)
    if card is None:
        raise KeyError("unknown callback card")
    for key in ("name", "case_type", "urgency_signal"):
        if key in fields and fields[key]:
            card[key] = fields[key]
    _log("updated", card)
    return card


def _sla_status(card: dict) -> dict:
    now = datetime.now(timezone.utc)
    due = datetime.fromisoformat(card["due_at"])
    remaining = (due - now).total_seconds()
    return {
        "sla_status": "overdue" if remaining < 0 else "on_time",
        "seconds_remaining": int(remaining),
    }


def list_callbacks() -> list[dict]:
    """Open cards first, oldest first — the queue staff work top-down.
    Each card carries its live SLA status so an overdue callback is
    visible at a glance."""
    open_cards = [c for c in _cards.values() if c["status"] == "open"]
    open_cards.sort(key=lambda c: c["created_at"])
    result = []
    for card in open_cards:
        view = dict(card)
        view.update(_sla_status(card))
        result.append(view)
    return result


def mark_called(card_id: str) -> dict:
    """Staff called the number. The card leaves the open queue but
    stays on record until the callback is resolved."""
    card = _cards.get(card_id)
    if card is None:
        raise KeyError("unknown callback card")
    card["status"] = "called"
    _log("called", card)
    return card


def resolve_callback(card_id: str) -> dict:
    """The callback reached the caller and the matter moved on."""
    card = _cards.get(card_id)
    if card is None:
        raise KeyError("unknown callback card")
    card["status"] = "done"
    _log("resolved", card)
    return card
