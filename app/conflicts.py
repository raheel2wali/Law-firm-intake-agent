"""The conflict check: the gate that makes this legal tech, not a chatbot.

Before the firm takes on any matter, every name in the room (the caller,
the opposing party, related entities) is checked against the firm's
conflict database: current clients, opposing parties, related matters,
even consultations that never became cases.

A hit is a hard stop. The intake halts, the caller gets a polite decline
with zero details about the match, and the attorney gets a notification
with the full details. Telling a stranger "we have a relationship with
the other side" would itself be a confidentiality breach.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# Suffixes that carry no identity: "Apex Construction LLC" == "Apex Construction".
_ORG_SUFFIXES = {
    "llc", "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "pllc", "pa", "esq", "esquire",
}


def normalize_name(name: str) -> str:
    """Collapse a name to its comparable core.

    Lowercase, strip accents, drop punctuation and org suffixes, and
    collapse whitespace. Handles the usual intake sloppiness:
    "APEX construction, LLC" and "Apex Construction" normalize alike.
    """
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s]", " ", name.lower())
    tokens = [t for t in name.split() if t not in _ORG_SUFFIXES]
    return " ".join(tokens)


def _token_overlap(a: str, b: str) -> float:
    """Cheap fuzzy match: share of tokens the two names have in common."""
    set_a, set_b = set(a.split()), set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / max(len(set_a), len(set_b))


# A name match at or above this counts as a hit. Tuned by eye on the
# sample file; real firms would tune this against their own docket.
MATCH_THRESHOLD = 0.75


def load_conflicts(path: str | Path | None = None) -> list[dict]:
    """Load the firm's conflict list.

    Real firms load this from their case management system. In this repo
    it is a sample file so the gate can be developed and tested.
    """
    path = Path(path or Path(__file__).resolve().parent.parent / "data" / "conflicts.sample.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["parties"]


def check_conflict(names: list[str], parties: list[dict] | None = None) -> list[dict]:
    """Return every conflict-database entry that matches any given name.

    Each hit carries the matched entry, the query name that triggered it,
    and the match score. Empty list means clear to proceed.
    """
    parties = parties if parties is not None else load_conflicts()
    hits = []
    for name in names:
        if not name or not name.strip():
            continue
        query = normalize_name(name)
        for party in parties:
            candidate = normalize_name(party["name"])
            score = _token_overlap(query, candidate)
            if score >= MATCH_THRESHOLD:
                hits.append({
                    "query_name": name,
                    "matched_name": party["name"],
                    "score": round(score, 2),
                    "role": party.get("role", ""),
                    "matter": party.get("matter", ""),
                })
    return hits


def names_in_intake(intake) -> list[str]:
    """Names worth checking from the qualification interview so far.

    The caller (who), plus any capitalized multi-word names mentioned in
    what happened (opposing parties usually surface there first).
    """
    names = [intake.who] if getattr(intake, "who", "") else []
    text = getattr(intake, "what", "") or ""
    for match in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        if match not in names:
            names.append(match)
    return names


def check_intake(intake, parties: list[dict] | None = None) -> list[dict]:
    """Run the conflict gate on a qualification interview. Hard stop on hit."""
    return check_conflict(names_in_intake(intake), parties)


def polite_decline() -> str:
    """What the caller hears on a conflict hit. Zero details about the match."""
    return (
        "Thanks for sharing the details with us. After a quick review, we're "
        "not able to take this matter on. Nothing you said is kept on file "
        "beyond this conversation, and we'd encourage you to reach out to "
        "another firm soon so your options stay open. Wishing you the best "
        "with your case."
    )


def attorney_alert(intake, hits: list[dict]) -> str:
    """The full-detail notification the attorney gets on a conflict hit."""
    lines = [
        "CONFLICT CHECK HIT — intake halted",
        "",
        intake.summary() if hasattr(intake, "summary") else "",
        "",
        "Matches:",
    ]
    for hit in hits:
        lines.append(
            f"- {hit['matched_name']} (role: {hit['role']}, "
            f"matter: {hit['matter']}, matched as '{hit['query_name']}', "
            f"score {hit['score']})"
        )
    lines.append("")
    lines.append(
        "Caller was given the standard decline. No details of the match "
        "were shared."
    )
    return "\n".join(lines)
