"""The qualification interview: extract case facts across turns,
track what's missing, and know when to stop asking and book.

Intake is an interview, not a chat. The attorney needs five facts:
who, what, when, where, and how urgent. Everything else is noise.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI

from app.conflicts import attorney_alert, check_intake, polite_decline

_client = OpenAI()

URGENT_PATTERNS = [
    r"arrest",
    r"jail",
    r"court.{0,20}(tomorrow|monday|tuesday|wednesday|thursday|friday|within|in \d+ (day|hour))",
    r"\b(48 hours|24 hours|tonight)\b",
    r"\b(er|emergency room|hospital)\b",
    r"\binjur",
]

REQUIRED_FACTS = ("who", "what", "when", "where", "urgency")


@dataclass
class Intake:
    who: str = ""
    what: str = ""
    when: str = ""
    where: str = ""
    urgency: str = ""          # "low" | "normal" | "high"
    turns: int = 0
    history: list[dict] = field(default_factory=list)

    def missing(self) -> list[str]:
        return [f for f in REQUIRED_FACTS if not getattr(self, f)]

    def complete(self) -> bool:
        return not self.missing()

    def summary(self) -> str:
        lines = [
            f"Who: {self.who or 'unknown'}",
            f"What: {self.what or 'unknown'}",
            f"When: {self.when or 'unknown'}",
            f"Where: {self.where or 'unknown'}",
            f"Urgency: {self.urgency or 'unknown'}",
        ]
        return "\n".join(lines)


def detect_urgency(text: str) -> str:
    lowered = text.lower()
    for pattern in URGENT_PATTERNS:
        if re.search(pattern, lowered):
            return "high"
    if any(w in lowered for w in ("asap", "urgent", "immediately", "deadline")):
        return "high"
    return "normal"


_EXTRACT_PROMPT = """Extract intake facts from the conversation below.
Return one line per fact, exactly in this format:
who: <name or relationship of caller, or empty>
what: <what happened, one short phrase, or empty>
when: <when it happened, or empty>
where: <where it happened, or empty>
urgency: <low, normal, or high>

Only fill in facts that are clearly stated. Never guess.
"""


def extract_facts(intake: Intake, caller_message: str) -> None:
    """Update the intake schema from the latest caller message."""
    intake.history.append({"role": "user", "content": caller_message,
                           "at": datetime.utcnow().isoformat()})
    transcript = "\n".join(
        f"{m['role']}: {m['content']}" for m in intake.history[-8:]
    )
    resp = _client.chat.completions.create(
        model=os.environ.get("ANSWER_MODEL", "gpt-4o-mini"),
        temperature=0,
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    for line in resp.choices[0].message.content.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key in REQUIRED_FACTS and value and value.lower() not in ("empty", "unknown"):
            if key == "urgency":
                value = value if value in ("low", "normal", "high") else "normal"
            setattr(intake, key, value)
    # Urgency gets a fast deterministic pass too; an arrest shouldn't
    # wait for the model to notice.
    if detect_urgency(caller_message) == "high":
        intake.urgency = "high"
    intake.turns += 1


def next_question(intake: Intake) -> str | None:
    """The single most important missing fact, or None if we should stop."""
    if intake.urgency == "high":
        return None  # stop asking, escalate
    if intake.turns >= 6:
        return None  # cap the interrogation; book with what we have
    missing = intake.missing()
    if not missing:
        return None
    prompts = {
        "who": "Can I get your name?",
        "what": "Tell me briefly what happened.",
        "when": "When did this happen?",
        "where": "Where did this happen?",
        "urgency": "Is there anything time-sensitive, like a court date coming up?",
    }
    return prompts[missing[0]]


def should_book(intake: Intake) -> bool:
    """Book when the facts are complete, or when urgency overrides."""
    return intake.urgency == "high" or intake.complete() or intake.turns >= 6


def run_turn(intake: Intake, caller_message: str) -> dict:
    """One full interview turn. Returns what to do next."""
    extract_facts(intake, caller_message)
    # The conflict check is a hard gate: it runs before anything can book,
    # and a hit stops the intake outright. Nothing proceeds past it.
    hits = check_intake(intake)
    if hits:
        intake.history.append({"role": "assistant", "content": polite_decline(),
                               "at": datetime.utcnow().isoformat()})
        return {"action": "decline", "message": polite_decline(),
                "alert": attorney_alert(intake, hits), "reason": "conflict"}
    if should_book(intake):
        return {"action": "book", "summary": intake.summary(),
                "reason": "urgent" if intake.urgency == "high" else "facts complete"}
    question = next_question(intake)
    intake.history.append({"role": "assistant", "content": question,
                           "at": datetime.utcnow().isoformat()})
    return {"action": "ask", "question": question, "summary": intake.summary()}
