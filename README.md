# LexIntake — AI Intake Agent for Law Firms

I'm building an AI intake agent for law firms, in public. This repo is the code companion to my 10-part LinkedIn series where I build it piece by piece: RAG over firm knowledge, a qualification dialog, conflict checks, booking tools, ethics guardrails, voice intake, evals, integrations, and shipping it.

## The problem

Law firms lose clients on missed calls and slow follow-ups. The firm that answers first usually wins the client. Intake staff drown in unqualified leads while good cases slip through. LexIntake answers every inquiry, qualifies the lead, runs a conflict check, books the consultation, and hands the attorney a clean intake summary.

One hard line: it never gives legal advice. That boundary shapes the entire build.

## What it will do (by the end of the series)

- Answer firm questions from the firm's own docs (RAG)
- Run a structured qualification interview (who / what / when / where / urgency)
- Check conflicts of interest before any engagement
- Book consultations and create matters via tools (with confirmation)
- Refuse legal advice and hand off to an attorney instead
- Cover the phones after hours with missed-call text-back

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY
uvicorn app.main:app --reload
```

```bash
curl localhost:8000/health
```

## The build log

- [x] Part 1: The Blueprint — repo skeleton, architecture, roadmap
- [x] Part 2: The Brain (RAG over firm knowledge)
- [x] Part 3: The Ears (qualification dialog)
- [x] Part 4: The Conflict Check
- [x] Part 5: The Hands (booking + matter tools)
- [ ] Part 6: Ethics Guardrails
- [ ] Part 7: The Voice Channel
- [ ] Part 8: Evals & Quality
- [ ] Part 9: Integrations
- [ ] Part 10: Ship It

## Part 2: The Brain (RAG over firm knowledge)

The agent can only say what the firm actually says. `data/firm_faqs.md` is
the source of truth: practice areas, fee structures, FAQs, office info.

- `app/ingest.py` loads the markdown docs, cleans them, and chunks them
  at 400 tokens with 50 overlap.
- `app/rag.py` embeds chunks into pgvector, retrieves top-8, reranks to
  top-3, and answers with per-answer citations.

The rule that matters: a wrong fee quote is a liability. If retrieval
can't support the question, the agent says it doesn't know and routes
to a human instead of inventing an answer.

```bash
export DATABASE_URL=postgresql://localhost:5432/lexintake
python -m app.rag   # init store + ingest data/
```

## Part 3: The Ears (qualification dialog)

Intake is an interview, not a chat. The attorney needs five facts:
who, what, when, where, and how urgent. Everything else is noise.

- `app/intake.py` holds the schema and the interview loop. Each turn
  extracts facts from what the caller said, tracks what's still missing,
  and asks only the single most important missing fact.
- Urgency is a fast deterministic check (arrest, ER, a court date within
  48 hours) that overrides the model. Urgent callers never wait for
  more questions.
- `should_book()` stops the interview when the facts are complete, the
  caller is urgent, or six turns have passed. The attorney gets a clean
  intake card: five lines, not five pages.

```python
from app.intake import Intake, run_turn

intake = Intake()
result = run_turn(intake, "I was in a car accident last night downtown")
# {"action": "ask", "question": "Can I get your name?", ...}
```

## Part 4: The Conflict Check

This is the gate that makes the project legal tech instead of a chatbot.
Before the firm takes on any matter, every name in the room is checked
against the firm's conflict database: current clients, opposing parties,
related matters, even consultations that never became cases.

- `app/conflicts.py` normalizes names (accents, punctuation, org
  suffixes) and fuzzy-matches them against the conflict list, so
  "Apex Construction LLC" and "Apex construction" still match.
- A hit is a hard stop: the intake halts, the caller gets a polite
  decline with zero details about the match, and the attorney gets a
  notification with the full details. Telling a stranger "we have a
  relationship with the other side" would itself be a breach.
- `data/conflicts.sample.json` is a fictional sample list for
  development. Real firms would load this from their case management
  system.
- The wiring lives in `run_turn()` in `app/intake.py`: the gate runs
  after fact extraction and before anything can book. Nothing proceeds
  past it.

```python
from app.intake import Intake, run_turn

intake = Intake()
result = run_turn(intake, "I'm Daniel Reyes, calling about the other driver, Apex Construction")
# {"action": "decline", "message": "Thanks for sharing...", "alert": "CONFLICT CHECK HIT...", "reason": "conflict"}
```

## Part 5: The Hands (booking + matter tools)

Understanding without action is just a very smart answering machine, so
LexIntake gets exactly three tools, and nothing else:

- `book_consultation` reserves a slot, after checking it is free first
- `create_matter` opens the matter with the intake card attached
- `send_followup` confirms, reminds, or reschedules by text or email

Three rules wrap every write:

1. **Read freely, write carefully.** Reads need no permission. Every write
   is proposed first and sits in a pending queue with a token; it only
   executes when approved through `POST /confirm`. Tokens expire after
   15 minutes.
2. **Dry-run mode for testing.** `DRY_RUN=1` points the tools at in-memory
   fakes, so the whole pipeline runs against a fake calendar and fake
   matters. With it off, the adapters raise `IntegrationNotWired` instead
   of pretending — the real calendar and case-management clients land in
   Part 9 (Integrations).
3. **Scoped permissions.** Each tool declares a scope
   (`write:calendar`, `write:matters`, `write:followups`); the deployment
   grants them via `LEXINTAKE_SCOPES`. Narrow it down in production.

Everything is audited: every proposal, approval, decline, and execution
lands in `data/audit.log.jsonl`, a trail a partner can skim in
30 seconds. Dry-run once caught a double-booking on a 60-second-stale
calendar cache; the slot is now re-read at booking time, not before.

```python
from app.intake import Intake, run_turn
from app.tools import run_booking, confirm_action

intake = Intake()
result = run_turn(intake, "...")   # {"action": "book", ...}
proposed = run_booking(result["summary"], slot="2026-10-21T10:00", contact="caller")
# each entry: {"status": "pending_confirmation", "token": "...", ...}
```

```bash
curl localhost:8000/pending
curl -X POST localhost:8000/confirm \
  -H 'Content-Type: application/json' \
  -d '{"token": "<token>", "approved": true}'
```
