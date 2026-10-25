"""Bonus Part 2: The Importer.

A firm that wants to pilot LexIntake usually has its data stuck in
1998: the conflicts list in an Excel sheet, FAQs scattered across the
website, matters in a spreadsheet nobody opens. Typing all of that in
by hand is how pilots die before they start.

The Importer takes a CSV upload for one of three kinds — conflicts,
faqs, or matters — and never writes silently. A dry-run preview first
shows what would be added, what is a duplicate, and what has a bad
format. Only an explicit apply call writes anything, following the
same "propose first" discipline as the Part 5 tools.

Expected CSV columns:
- conflicts: name, role, matter (name is required)
- faqs: question, answer (both required)
- matters: title, client, status (title is required)

Duplicates are checked against what the firm already has: normalized
names for conflicts (same normalization as the Part 4 gate), exact
question text for FAQs, exact titles for matters.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from app.conflicts import load_conflicts, normalize_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COLUMNS = {
    "conflicts": ("name", "role", "matter"),
    "faqs": ("question", "answer"),
    "matters": ("title", "client", "status"),
}

REQUIRED = {
    "conflicts": ("name",),
    "faqs": ("question", "answer"),
    "matters": ("title",),
}


def _read_rows(csv_text: str) -> tuple[list[dict], list[str]]:
    """Parse CSV text. Returns (rows, errors); a missing header or an
    unreadable row is an error, never a silent skip."""
    try:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
    except csv.Error as exc:
        return [], [f"could not parse CSV: {exc}"]
    if reader.fieldnames is None:
        return [], ["empty CSV: no header row"]
    rows = [dict(r) for r in reader if any((v or "").strip() for v in r.values())]
    return rows, []


def _existing(kind: str) -> set[str]:
    """Keys already in the firm's data, for duplicate detection."""
    if kind == "conflicts":
        return {normalize_name(p["name"]) for p in load_conflicts()}
    if kind == "faqs":
        faqs_path = DATA_DIR / "firm_faqs.md"
        if not faqs_path.exists():
            return set()
        text = faqs_path.read_text(encoding="utf-8")
        return {
            line[3:].strip().lower()
            for line in text.splitlines()
            if line.startswith("Q: ")
        }
    matters_path = DATA_DIR / "matters.jsonl"
    if not matters_path.exists():
        return set()
    titles = set()
    for line in matters_path.read_text(encoding="utf-8").splitlines():
        try:
            titles.add(json.loads(line)["title"].strip().lower())
        except (KeyError, ValueError):
            continue
    return titles


def _row_key(kind: str, row: dict) -> str:
    if kind == "conflicts":
        return normalize_name(row.get("name", ""))
    if kind == "faqs":
        return (row.get("question") or "").strip().lower()
    return (row.get("title") or "").strip().lower()


def preview_import(kind: str, csv_text: str) -> dict:
    """Dry-run preview. Writes nothing. Returns what would be added,
    what is already there, and what is malformed."""
    if kind not in COLUMNS:
        raise ValueError(f"unknown import kind {kind!r}; use conflicts, faqs, or matters")
    rows, errors = _read_rows(csv_text)
    seen = _existing(kind)
    to_add: list[dict] = []
    duplicates: list[dict] = []
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        clean = {k: (row.get(k) or "").strip() for k in COLUMNS[kind]}
        missing = [f for f in REQUIRED[kind] if not clean[f]]
        if missing:
            errors.append(f"line {i}: missing {', '.join(missing)}")
            continue
        key = _row_key(kind, clean)
        if key in seen:
            duplicates.append(clean)
            continue
        seen.add(key)
        to_add.append(clean)
    return {"kind": kind, "to_add": to_add, "duplicates": duplicates,
            "errors": errors, "total_rows": len(rows)}


def apply_import(kind: str, csv_text: str) -> dict:
    """Apply a previewed import. Rows with errors or duplicates are
    left out; only clean, new rows are written."""
    preview = preview_import(kind, csv_text)
    if preview["errors"]:
        return {**preview, "applied": 0,
                "note": "nothing written: fix the errors and re-apply"}
    if kind == "conflicts":
        path = DATA_DIR / "conflicts.sample.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in preview["to_add"]:
            data["parties"].append(row)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    elif kind == "faqs":
        path = DATA_DIR / "firm_faqs.md"
        with path.open("a", encoding="utf-8") as fh:
            for row in preview["to_add"]:
                fh.write(f"\nQ: {row['question']}\nA: {row['answer']}\n")
    else:
        path = DATA_DIR / "matters.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for row in preview["to_add"]:
                fh.write(json.dumps(row) + "\n")
    return {**preview, "applied": len(preview["to_add"])}
