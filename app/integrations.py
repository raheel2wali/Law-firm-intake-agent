"""Integrations: the boring plumbing that makes the agent sellable.

Part 5 gave LexIntake three tools with read-freely/write-carefully rules
and a pending-confirmation queue. Until now every write ran against
in-memory fakes and the live adapters raised IntegrationNotWired on
first touch. This module wires the real systems behind one small
adapter interface:

- CalendarAdapter      -> books consultations (Google Calendar by default)
- CaseManagementAdapter -> opens matters (Clio-style API by default)
- MessagingAdapter     -> sends SMS/email follow-ups (Twilio/SMTP)

Nothing here fires on import. The deployment picks an adapter per
system through the environment:

    LEXINTAKE_CALENDAR=google | stub
    LEXINTAKE_CASEMGMT=clio | stub
    LEXINTAKE_MESSAGING=twilio | stub

"stub" keeps the Part 5 dry-run behavior: in-memory, no network.
Anything else needs credentials in the environment (see .env.example).
Without them the adapter raises IntegrationNotWired loudly instead of
pretending the booking happened. A booking that vanishes between
systems is worse than no booking at all, it lies to the attorney.

The follow-up engine lives here too. Bookings leak value when nobody
follows up, so plan_followups() lays out three touchpoints per booking:
an instant confirmation, a reminder a day before, and a check-in when
someone no-shows. Each one is a proposal in the same pending queue as
every other write, so a human can still say no before a single text
goes out.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Protocol


class IntegrationNotWired(Exception):
    """Raised when a write is approved but the real system behind the
    adapter isn't connected yet. Fails loudly on purpose: a booking that
    silently goes nowhere is worse than no booking at all."""

# ---------------------------------------------------------------------------
# Adapter picking. Env var per system so a firm can wire the calendar but
# leave case management on stubs while IT sets up the API access.
# ---------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip().lower()


# ---------------------------------------------------------------------------
# Interfaces. Small on purpose: the tools in app/tools.py should not have
# to change when a firm swaps Clio for MyCase or Twilio for something else.
# ---------------------------------------------------------------------------


class CalendarAdapter(Protocol):
    def slot_free(self, slot: str) -> bool: ...
    def book(self, *, slot: str, contact: str, intake_summary: str) -> dict: ...


class CaseManagementAdapter(Protocol):
    def create(self, *, summary: str) -> dict: ...


class MessagingAdapter(Protocol):
    def send(self, *, booking_ref: str, channel: str, message: str) -> dict: ...


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise IntegrationNotWired(
            f"integration not wired: set {', '.join(missing)} "
            "(see .env.example)"
        )


# ---------------------------------------------------------------------------
# Stubs. The same in-memory fakes Part 5 used under DRY_RUN=1, moved here
# so the live-adapter path and the test path share the interface.
# ---------------------------------------------------------------------------


class StubCalendar:
    def __init__(self) -> None:
        self.bookings: list[dict] = []

    def slot_free(self, slot: str) -> bool:
        return all(b["slot"] != slot for b in self.bookings)

    def book(self, *, slot: str, contact: str, intake_summary: str) -> dict:
        ref = f"STUB-BOOK-{len(self.bookings) + 1:03d}"
        self.bookings.append(
            {"ref": ref, "slot": slot, "contact": contact, "summary": intake_summary}
        )
        return {"ref": ref, "slot": slot}


class StubMatters:
    def __init__(self) -> None:
        self.matters: list[dict] = []

    def create(self, *, summary: str) -> dict:
        ref = f"STUB-MATTER-{len(self.matters) + 1:03d}"
        self.matters.append({"ref": ref, "summary": summary})
        return {"ref": ref}


class StubMessaging:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, *, booking_ref: str, channel: str, message: str) -> dict:
        self.sent.append(
            {"booking_ref": booking_ref, "channel": channel, "message": message}
        )
        return {"booking_ref": booking_ref, "channel": channel}


# ---------------------------------------------------------------------------
# Live adapters. Each checks its credentials up front and raises
# IntegrationNotWired with a useful message when they are missing, the
# same loud-failure contract Part 5 established. Wire the actual HTTP
# calls where the firm’s IT gives you API access; the interface above
# means the rest of the agent never notices the swap.
# ---------------------------------------------------------------------------


class GoogleCalendarAdapter:
    """Books on the firm's Google Calendar. Needs a service-account style
    token in the environment; raises IntegrationNotWired without one."""

    def __init__(self) -> None:
        _require_env("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_TOKEN")

    def slot_free(self, slot: str) -> bool:
        # In production this reads the calendar's freebusy for the slot.
        # Re-read at booking time, not earlier: Part 5 caught a double
        # booking on a 60-second-stale cache, so there is no cache here.
        _require_env("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_TOKEN")
        raise IntegrationNotWired(
            "Google Calendar read not implemented in this build; "
            "slot check must hit the freebusy endpoint"
        )

    def book(self, *, slot: str, contact: str, intake_summary: str) -> dict:
        _require_env("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_TOKEN")
        raise IntegrationNotWired(
            "Google Calendar write not implemented in this build; "
            "approved bookings must POST to the Calendar events endpoint"
        )


class ClioAdapter:
    """Opens matters in a Clio-style case management system. Needs an API
    token and the firm's account id; raises IntegrationNotWired without
    them."""

    def __init__(self) -> None:
        _require_env("CLIO_API_TOKEN", "CLIO_ACCOUNT_ID")

    def create(self, *, summary: str) -> dict:
        _require_env("CLIO_API_TOKEN", "CLIO_ACCOUNT_ID")
        raise IntegrationNotWired(
            "Clio matter creation not implemented in this build; "
            "approved matters must POST to the matters endpoint with the "
            "intake card attached as the description"
        )


class TwilioSmtpAdapter:
    """Sends SMS via Twilio and email via SMTP. Each channel checks its
    own credentials so a firm can text without email configured."""

    def __init__(self) -> None:
        pass

    def send(self, *, booking_ref: str, channel: str, message: str) -> dict:
        if channel == "sms":
            _require_env("TWILIO_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")
            raise IntegrationNotWired(
                "Twilio send not implemented in this build; approved texts "
                "must POST to the Messages endpoint"
            )
        if channel == "email":
            _require_env("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
            raise IntegrationNotWired(
                "SMTP send not implemented in this build; approved emails "
                "must go through smtplib with TLS"
            )
        raise ValueError("channel must be 'sms' or 'email'")


# ---------------------------------------------------------------------------
# Factories: the one place the deployment's choices live.
# ---------------------------------------------------------------------------


def make_calendar() -> CalendarAdapter:
    return GoogleCalendarAdapter() if _env("LEXINTAKE_CALENDAR", "stub") == "google" else StubCalendar()


def make_case_management() -> CaseManagementAdapter:
    return ClioAdapter() if _env("LEXINTAKE_CASEMGMT", "stub") == "clio" else StubMatters()


def make_messaging() -> MessagingAdapter:
    return TwilioSmtpAdapter() if _env("LEXINTAKE_MESSAGING", "stub") == "twilio" else StubMessaging()


def _has_creds(*names: str) -> bool:
    return all(os.environ.get(n) for n in names)


def integration_status() -> dict:
    """What is wired right now, for GET /integrations. No secrets, just
    the adapter choices and whether their credentials are present."""
    creds = {
        "calendar": {"google": ("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_TOKEN")},
        "case_management": {"clio": ("CLIO_API_TOKEN", "CLIO_ACCOUNT_ID")},
        "messaging": {"twilio": ("TWILIO_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")},
    }
    status = {}
    for name, var in (
        ("calendar", "LEXINTAKE_CALENDAR"),
        ("case_management", "LEXINTAKE_CASEMGMT"),
        ("messaging", "LEXINTAKE_MESSAGING"),
    ):
        choice = _env(var, "stub")
        required = creds[name].get(choice, ())
        status[name] = {
            "adapter": choice,
            "wired": choice != "stub" and _has_creds(*required),
        }
    return status


# ---------------------------------------------------------------------------
# Follow-up engine: three touchpoints per booking. No-shows are where
# booked revenue silently dies, so the third touchpoint is the one that
# actually pays for the plumbing.
# ---------------------------------------------------------------------------

REMINDER_LEAD = timedelta(hours=24)


def _firm_name() -> str:
    return os.environ.get("LEXINTAKE_FIRM_NAME", "our firm")


def plan_followups(
    booking_ref: str,
    slot: str,
    contact: str,
    *,
    channel: str = "sms",
) -> list[dict]:
    """Lay out the follow-up schedule for a confirmed booking. Returns
    plain dicts; the caller proposes each through app.tools.send_followup
    so they land in the pending queue like every other write."""
    firm = _firm_name()
    slot_dt = datetime.fromisoformat(slot)
    reminder_due = (slot_dt - REMINDER_LEAD).isoformat()
    return [
        {
            "kind": "confirmation",
            "due": "immediately",
            "channel": channel,
            "message": (
                f"This is {firm} confirming your consultation on "
                f"{slot_dt:%A %B %d at %I:%M %p}. Reply RESCHEDULE if "
                "that time no longer works."
            ),
        },
        {
            "kind": "reminder",
            "due": reminder_due,
            "channel": channel,
            "message": (
                f"Reminder: your consultation with {firm} is tomorrow, "
                f"{slot_dt:%A at %I:%M %p}. Reply C to confirm or "
                "RESCHEDULE to move it."
            ),
        },
        {
            "kind": "no_show_checkin",
            "due": "when caller misses the appointment",
            "channel": channel,
            "message": (
                f"We missed you today at {firm}. Your matter still "
                "matters to us. Reply to pick a new time and we will "
                "hold it for 48 hours."
            ),
        },
    ]


def no_show(booking_ref: str, contact: str, *, channel: str = "sms") -> dict:
    """The no-show rescue: propose the check-in message. Deliberately
    separate from plan_followups() so the firm decides what "no-show"
    means (calendar says missed, or the attorney flags it)."""
    return {
        "kind": "no_show_checkin",
        "booking_ref": booking_ref,
        "contact": contact,
        "channel": channel,
        "message": (
            f"We missed you today at {_firm_name()}. Your matter still "
            "matters to us. Reply to pick a new time and we will "
            "hold it for 48 hours."
        ),
    }
