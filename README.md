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
- [x] Part 6: Ethics Guardrails
- [x] Part 7: The Voice Channel
- [x] Part 8: Evals & Quality
- [x] Part 9: Integrations
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

## Part 6: Ethics Guardrails

The non-negotiable part: this agent never gives legal advice. Not a
hint, not a guess — one wrong answer would be the unauthorized practice
of law, and the firm owns every word the agent says.

The guardrails are deliberately dumb. Pattern matching is the point:
the refusal has to hold even when the model really wants to help.

- **Advice firewall.** `guard_turn()` runs on every user message before
  the LLM ever sees it. Advice-seeking phrasings ("do I have a case",
  "should I sue", "just tell me yes") get a plain refusal plus an
  offer to book a consultation. The net is intentionally wide here —
  a false positive just means a human reviews it.
- **Disclaimer on every conversation.** "I'm an intake assistant, not
  an attorney." No fine print.
- **Attorney review queue.** Advice-seeking callers who keep pushing
  don't get argued with — the redacted transcript lands in
  `data/review_queue.jsonl` for human eyes first.
- **PII redaction.** SSNs, emails, and phone numbers are stripped with
  `redact_pii()` before anything is logged or queued. Everything
  downstream only sees the redacted version.
- **Prompt-injection tripwires.** "Ignore your instructions", roleplay
  tricks, override attempts — checked first, because an injected
  message can imitate anything, including an advice request. Hard stop,
  not a cleverer answer.

`evals/eval_basic.py` is the eval harness for the risky conversations:
the desperate caller, the polite injection, the roleplay trick, plus
redaction checks. 12/12 passing. Guardrails that are never tested are
just wishes — new failure modes get a new case here before they get a
fix.

```bash
python evals/eval_basic.py
```

## Part 7: The Voice Channel

Most intakes start as phone calls, so this week LexIntake got a voice
front door. Two paths in, one pipeline out:

- **After-hours answering.** The provider posts every call to
  `POST /voice`. An answered call runs its transcript through the same
  interview loop from Parts 1-6: qualification, the conflict check, and
  the ethics guardrails all ride along.
- **Missed-call text-back.** A rang-out call texts back within the
  minute ("sorry we missed you, tell me what this is about") and opens
  a partial intake, so the caller's reply picks up where the ringing
  stopped instead of landing in Monday's voicemail pile.

`app/voice.py` holds the glue: payload normalization, the text-back,
and `run_transcript()`, which feeds transcribed caller turns through
`run_turn()` with `guard_turn()` on every segment. The caller on a
shaky midnight call is exactly who might ask "do I have a case"; the
refusal policy doesn't care which channel it came in on.

The telephony itself stays with the provider. Nothing here dials or
texts for real — the live adapters land with the real integrations in
Part 9.

```python
from app.voice import run_transcript

result = run_transcript("+15551234567", [
    "I was in a car accident last night downtown",
    "My name is Daniel Reyes",
])
# {"action": "book", "replies": [...], "summary": "..."}
```

```bash
curl -X POST localhost:8000/voice \
  -H 'Content-Type: application/json' \
  -d '{"CallSid": "CA123", "From": "+15551234567", "CallStatus": "no-answer"}'
```

## Part 8: Evals & Quality

A friendly-sounding intake can still be a bad intake. So I stopped
grading on vibes and built a quality loop with three scores:

- **Completeness** — did the intake capture who / what / when / where /
  urgency? A five-fact fraction, nothing more.
- **Qualification accuracy** — did we route to the right practice area
  with the right priority? The urgency the caller stated drives the
  priority, deterministically.
- **Consultation show-rate** — of the appointments the agent booked,
  how many callers actually showed up? A booked consult nobody attends
  is worse than a missed call.

`app/quality.py` holds the graders plus the intake log: every intake
lands in `data/intakes.jsonl`, and `GET /stats` aggregates the three
scores over everything the agent has ever booked.

`evals/eval_quality.py` is the mystery-shopper set: 25 scripted caller
personas (the 2 AM rear-ended caller, the arrest tonight, the terse
caller who gives you three words, the caller the deterministic matcher
can't classify). Every persona runs through the same graders with an
accuracy floor, and exit code 0 requires all of them green.

The feedback loop that matters: `quality.add_regression_case()` promotes
any bad intake from production into `data/eval_regressions.jsonl`, and
the eval harness runs over those cases too. The suite keeps every
mistake the system ever made, so it can never regress silently. New
failure modes get a case before they get a fix — same rule as the
ethics harness in Part 6.

```bash
python evals/eval_quality.py   # 25/25 mystery shoppers green
```

```bash
curl localhost:8000/stats
# {"total_intakes": ..., "avg_completeness": ..., "qualification_accuracy": ..., "consultation_show_rate": ...}
```

## Part 9: Integrations

An agent that lives alone dies alone. All the clever parts before this
one end at a proposed booking; this part is where the proposal actually
lands in the firm's systems.

- **One adapter interface, three connectors.** `app/integrations.py`
  defines `CalendarAdapter`, `CaseManagementAdapter`, and
  `MessagingAdapter`, with Google Calendar, a Clio-style case
  management API, and Twilio/SMTP messaging as the default live
  adapters. The deployment picks per system through `LEXINTAKE_CALENDAR`,
  `LEXINTAKE_CASEMGMT`, and `LEXINTAKE_MESSAGING`, so a firm can wire the
  calendar but leave case management on stubs while IT sets up access.
- **Loud failure, never silent.** Every live adapter checks its
  credentials up front and raises `IntegrationNotWired` without them.
  A booking that vanishes between systems is worse than no booking at
  all, it lies to the attorney. The slot check re-reads the calendar at
  booking time; there is no stale cache (Part 5 already caught that
  bug once).
- **The follow-up engine.** `plan_followups()` lays out three
  touchpoints per booking: an instant confirmation, a reminder a day
  before, and a check-in when someone no-shows. Each one is proposed
  through the same pending-confirmation queue as every other write, so
  a human can still say no before a single text goes out.
- **Tools wiring.** `app/tools.py` now resolves its adapters from here:
  stubs in dry-run mode, the environment-picked adapters otherwise,
  constructed lazily so missing credentials fail at execution time.

```bash
curl localhost:8000/integrations
# {"calendar": {"adapter": "stub", "wired": false}, ...}
```

```python
from app.integrations import plan_followups, no_show

plan_followups("STUB-BOOK-001", "2026-10-26T10:00", "+15551234567")
# [{"kind": "confirmation", ...}, {"kind": "reminder", ...}, {"kind": "no_show_checkin", ...}]

no_show("STUB-BOOK-001", "+15551234567")
# {"kind": "no_show_checkin", "message": "We missed you today ..."}
```
