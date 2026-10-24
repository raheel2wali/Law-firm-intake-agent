# LexIntake — deployment notes (Part 10: Ship It)

How to run a pilot with a real firm. Nothing here is clever on
purpose: a pilot that breaks quietly is worse than no pilot at all.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For a real deployment, put uvicorn behind gunicorn with a couple of
workers and a process manager that restarts it. One worker is fine
for a single-firm pilot; the intake loop is not the bottleneck, the
phone provider's webhook retries are.

## Environment

| Variable | What it does |
| --- | --- |
| `OPENAI_API_KEY` | Model calls for the interview loop |
| `DATABASE_URL` | pgvector store for firm knowledge (Part 2) |
| `DRY_RUN=1` | Tools hit in-memory fakes, nothing real is booked |
| `LEXINTAKE_SCOPES` | Which writes the deployment may perform |
| `LEXINTAKE_CALENDAR` | Calendar adapter pick (Part 9) |
| `LEXINTAKE_CASEMGMT` | Case-management adapter pick (Part 9) |
| `LEXINTAKE_MESSAGING` | Messaging adapter pick (Part 9) |

Start every pilot in dry-run mode. Flip it off only after the firm
has watched a full intake end to end: call in, qualify, conflict
check, book, confirm. The pending-confirmation queue (Part 5) stays
on in production too. It is the cheapest safety net in the system.

## Before you ship checklist

1. `python evals/eval_basic.py` — ethics harness, 12/12 green.
2. `python evals/eval_quality.py` — mystery shoppers, 25/25 green.
3. `GET /integrations` — every adapter the firm expects is wired,
   and the ones that are not say so loudly instead of silently.
4. `GET /stats` — baseline the three quality scores on day one, so
   week two has something honest to compare against.
5. Check `data/review_queue.jsonl` daily at first. Advice-seeking
   callers land there redacted; a human reads them before anything
   else happens.

## What to watch in week one

- Show-rate on booked consultations (Part 8's third score). A booked
  consult nobody attends is the first sign the reminder flow is off.
- The review queue volume. A spike means callers are asking for
  advice the agent keeps refusing, which usually means the firm's
  FAQ docs need a better "what happens next" answer, not a looser
  guardrail.
- Every bad intake becomes a regression case before it gets a fix
  (Part 8). The pilot's job is to find those cases, not to look
  flawless.

## Data files

- `data/firm_faqs.md` — the firm's own words, the RAG source of truth.
- `data/conflicts.sample.json` — fictional sample only. Real firms
  load conflicts from their case-management system.
- `data/intakes.jsonl` — every intake, feeds `/stats`.
- `data/audit.log.jsonl` — every proposal, approval, decline, and
  execution. A partner can skim it in 30 seconds.
- `data/review_queue.jsonl` — redacted advice-seeking transcripts.

Keep these out of git in production. They hold real caller details
the moment a pilot goes live.
