"""Evals & Quality (Part 8): how do we know an intake was good?

A friendly-sounding intake can still be a bad intake. We grade every
intake on three scores instead of vibes:

- completeness: did we capture who / what / when / where / urgency?
- qualification accuracy: did we route to the right practice area
  with the right priority?
- consultation show-rate: of the appointments we booked, how many
  callers actually showed up?

Intakes land in a JSONL log (data/intakes.jsonl). GET /stats aggregates
them. Bad intakes in production get promoted to regression cases in
data/eval_regressions.jsonl, and the mystery-shopper eval set in
evals/eval_quality.py runs over all of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_FACTS = ("who", "what", "when", "where", "urgency")

INTAKES_LOG = Path(__file__).resolve().parent.parent / "data" / "intakes.jsonl"
REGRESSIONS_LOG = Path(__file__).resolve().parent.parent / "data" / "eval_regressions.jsonl"

# keyword -> practice area. Deliberately small and dumb: it has to be
# deterministic for the eval harness, and it only needs to cover what
# the firm's sample FAQs describe. Real classification is a Part 9+
# problem once we have enough labeled intakes.
PRACTICE_KEYWORDS = {
    "personal_injury": ["accident", "injury", "injured", "crash", "hurt", "collision", "slip", "fall", "rear-end", "rear-ended", "hit me"],
    "family": ["divorce", "custody", "child support", "alimony", "marriage"],
    "criminal": ["arrest", "arrested", "duii", "dui", "dwi", "jail", "charged", "bail"],
    "immigration": ["visa", "green card", "asylum", "deportation", "citizenship"],
    "estate": ["will", "trust", "probate", "estate"],
    "employment": ["fired", "terminated", "wrongful termination", "harassment", "harass", "harassing", "wage"],
    "corporate": ["contract", "incorporate", "llc", "business"],
}

URGENCY_PRIORITY = {"low": "routine", "normal": "standard", "high": "urgent"}


def completeness_score(intake: dict) -> float:
    """Fraction of the five required facts the intake captured (0.0-1.0)."""
    filled = sum(1 for f in REQUIRED_FACTS if str(intake.get(f, "")).strip())
    return round(filled / len(REQUIRED_FACTS), 2)


def classify_practice(transcript: str) -> str:
    """Best-guess practice area from keywords. Returns 'unknown' on a miss."""
    text = transcript.lower()
    best, hits = "unknown", 0
    for area, keywords in PRACTICE_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", text))
        if score > hits:
            best, hits = area, score
    return best


def expected_priority(urgency: str) -> str:
    """Urgency should drive the booking priority, deterministically."""
    return URGENCY_PRIORITY.get(urgency, "standard")


def qualification_correct(intake: dict, transcript: str) -> bool:
    """True when practice area and priority match what the transcript says."""
    area_ok = intake.get("practice_area") == classify_practice(transcript)
    priority_ok = intake.get("priority") == expected_priority(intake.get("urgency", ""))
    return area_ok and priority_ok


def log_intake(intake: dict, showed_up: bool | None = None) -> dict:
    """Append an intake outcome to the log. showed_up stays None until the
    consultation happens (or not); the firm marks it later."""
    record = {
        **intake,
        "completeness": completeness_score(intake),
        "qualified_ok": qualification_correct(intake, intake.get("transcript", "")),
        "showed_up": showed_up,
    }
    INTAKES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(INTAKES_LOG, "a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def read_intakes() -> list[dict]:
    if not INTAKES_LOG.exists():
        return []
    return [json.loads(line) for line in INTAKES_LOG.read_text().splitlines() if line.strip()]


def add_regression_case(persona: dict) -> None:
    """A bad intake from production becomes a permanent eval case. This is
    the feedback loop: the harness keeps every mistake the system ever made,
    so it can never regress silently."""
    REGRESSIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(REGRESSIONS_LOG, "a") as fh:
        fh.write(json.dumps(persona) + "\n")


def aggregate_stats() -> dict:
    """What GET /stats serves: the three quality scores over everything
    the agent has ever booked."""
    intakes = read_intakes()
    booked = [i for i in intakes if i.get("booked")]
    resolved = [i for i in booked if i.get("showed_up") is not None]
    return {
        "total_intakes": len(intakes),
        "booked_consultations": len(booked),
        "avg_completeness": (
            round(sum(i["completeness"] for i in intakes) / len(intakes), 2) if intakes else 0.0
        ),
        "qualification_accuracy": (
            round(sum(1 for i in intakes if i.get("qualified_ok")) / len(intakes), 2)
            if intakes
            else 0.0
        ),
        "consultation_show_rate": (
            round(sum(1 for i in resolved if i["showed_up"]) / len(resolved), 2)
            if resolved
            else None
        ),
    }
