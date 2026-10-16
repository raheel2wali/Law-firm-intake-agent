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
- [ ] Part 3: The Ears (qualification dialog)
- [ ] Part 4: The Conflict Check
- [ ] Part 5: The Hands (booking + matter tools)
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
