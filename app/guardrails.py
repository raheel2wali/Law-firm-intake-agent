"""Ethics guardrails: the non-negotiable part.

LexIntake answers phones, qualifies leads, and books consultations. It
never gives legal advice — that would be the unauthorized practice of
law, and the firm owns every word the agent says.

So the most important checks in the whole build are the dumb ones: a
deterministic advice firewall that runs before the LLM ever sees the
question, a disclaimer on every conversation, a review queue for
callers who keep pushing for legal guidance, PII redaction before
anything is logged, and tripwires for prompt injection.

None of this is a model. Pattern matching is the point: the refusal
has to hold even when the model really wants to help.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DISCLAIMER = (
    "Quick note: I'm an intake assistant, not an attorney, so I can't "
    "give legal advice. I can take down your details and book you a "
    "consultation with the firm."
)

ADVICE_REFUSAL = (
    "I can't answer that one — I'm not allowed to give legal advice, "
    "even a general answer. What I can do is book you a consultation "
    "with an attorney, who can actually look at your situation. Want me "
    "to find you a slot?"
)

INJECTION_REFUSAL = (
    "I'm going to stop there. I can't follow instructions tucked into "
    "messages like that. If you'd like, I can still take your details "
    "and book you a consultation."
)

# Advice-seeking phrasings, tuned on the intake conversations a firm
# actually gets. Lowercased, checked as substrings, so the net is wide —
# in this one spot, a false positive just means a human reviews it.
ADVICE_PATTERNS = (
    "do i have a case",
    "do i have a claim",
    "do i have a lawsuit",
    "should i sue",
    "should i settle",
    "should i sign",
    "what are my chances",
    "what is my case worth",
    "how much is my case worth",
    "can i win",
    "will i win",
    "is this legal",
    "is it legal",
    "am i liable",
    "am i at fault",
    "who is at fault",
    "what should i do",
    "tell me what to do",
    "what would you do",
    "give me legal advice",
    "just tell me yes",
    "just say yes",
    "between you and me",
    "off the record",
)

# Inputs that try to steer the agent off its rails. Again, substring
# matching and a wide net — flagging an innocent message is cheap,
# missing an injected one is not.
INJECTION_PATTERNS = (
    "ignore your instructions",
    "ignore all instructions",
    "disregard your instructions",
    "forget your instructions",
    "you are now",
    "pretend to be",
    "act as if",
    "roleplay as",
    "system prompt",
    "developer prompt",
    "reveal your prompt",
    "show your instructions",
    "do not follow",
    "override your",
    "jailbreak",
    "roleplay",
    "dan mode",
)

_PII_RULES = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"), "[PHONE]"),
)


def redact_pii(text: str) -> str:
    """Strip identifiers before anything is logged or queued.

    SSNs, emails, phone numbers. Everything downstream (logs, review
    queue, model context) should only ever see the redacted version.
    """
    for pattern, replacement in _PII_RULES:
        text = pattern.sub(replacement, text)
    return text


def asks_for_advice(text: str) -> bool:
    """Does this message ask the agent for legal advice?"""
    lowered = text.lower()
    return any(pattern in lowered for pattern in ADVICE_PATTERNS)


def looks_like_injection(text: str) -> bool:
    """Does this message try to override the agent's instructions?"""
    lowered = text.lower()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)


REVIEW_QUEUE_PATH = Path(__file__).resolve().parent.parent / "data" / "review_queue.jsonl"


def queue_for_review(text: str, reason: str) -> None:
    """Flag a conversation for attorney eyes first.

    Advice-seeking callers who keep pushing don't get argued with — the
    (redacted) transcript goes to a human. Store is JSONL so a partner
    can skim it without any tooling.
    """
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "redacted_text": redact_pii(text),
    }
    with open(REVIEW_QUEUE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def guard_turn(text: str) -> dict:
    """Run every guardrail on one user message, before the LLM sees it.

    Returns the action to take and what the caller should hear. Order
    matters: injection is checked first, because an injected message can
    imitate anything, including an advice request.
    """
    if looks_like_injection(text):
        queue_for_review(text, reason="prompt_injection")
        return {"action": "hard_stop", "message": INJECTION_REFUSAL}

    if asks_for_advice(text):
        queue_for_review(text, reason="advice_seeking")
        return {"action": "decline_advice", "message": ADVICE_REFUSAL}

    return {"action": "ok", "message": ""}


def with_disclaimer(reply: str) -> str:
    """Prefix the standard disclaimer to a reply, once per conversation."""
    return f"{DISCLAIMER}\n\n{reply}"
