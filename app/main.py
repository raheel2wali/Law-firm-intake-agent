"""FastAPI front door: a health check, the confirmation endpoint that
approves the agent's proposed writes (Part 5: The Hands), the voice
webhook that feeds phone calls into the intake pipeline (Part 7), and
the quality dashboard endpoint (Part 8: Evals & Quality). Part 10
adds a root endpoint so a firm checking the deployment sees what is
running instead of a 404.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import callbacks, importer, integrations, quality, tools, voice
from app.tools import IntegrationNotWired, ScopeDenied

app = FastAPI(title="LexIntake")


@app.get("/")
def index() -> dict:
    """What this deployment serves. Useful on day one of a pilot."""
    return {
        "service": "lexintake",
        "endpoints": [
            "/health",
            "/pending",
            "/confirm",
            "/stats",
            "/integrations",
            "/voice",
            "/callbacks",
            "/import",
        ],
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "lexintake"}


@app.get("/pending")
def pending() -> dict:
    """Everything the agent has proposed but nobody has confirmed yet."""
    return {"pending": tools.list_pending()}


class ConfirmRequest(BaseModel):
    token: str
    approved: bool
    note: str = ""


@app.post("/confirm")
def confirm(req: ConfirmRequest) -> dict:
    """Approve or decline a proposed write. The agent can never execute a
    write on its own; it always waits for this endpoint."""
    try:
        return tools.confirm_action(req.token, approved=req.approved, note=req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown or expired token")
    except ScopeDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except IntegrationNotWired as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@app.get("/stats")
def stats() -> dict:
    """The quality dashboard (Part 8): the three scores over everything
    the agent has ever booked — completeness, qualification accuracy,
    and consultation show-rate. If these are moving in the right
    direction, the intake is getting better."""
    return quality.aggregate_stats()


@app.get("/integrations")
def integration_status() -> dict:
    """Which systems are wired right now (Part 9): calendar, case
    management, messaging. A firm can wire the calendar but leave case
    management on stubs while IT sets up API access."""
    return integrations.integration_status()


@app.post("/voice")
def voice_webhook(payload: dict) -> dict:
    """A telephony provider posts here on every call event.

    - Answered after hours: run the transcript through the intake loop.
    - Missed: text back within the minute and open a partial intake, so
      the caller's reply picks up where the ringing stopped.
    """
    status = payload.get("CallStatus", "completed")
    if status in ("no-answer", "busy", "failed"):
        return voice.handle_missed_call(payload)
    return voice.handle_voice_call(payload)


@app.get("/callbacks")
def callbacks_queue() -> dict:
    """Bonus Part 1: the callback queue. Open cards oldest first, each
    with its live 2-minute SLA status."""
    return {"callbacks": callbacks.list_callbacks()}


@app.post("/callbacks/{card_id}/called")
def callback_called(card_id: str) -> dict:
    """Staff called the number; the card leaves the open queue."""
    try:
        return callbacks.mark_called(card_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown callback card")


@app.post("/callbacks/{card_id}/resolved")
def callback_resolved(card_id: str) -> dict:
    """The callback reached the caller and the matter moved on."""
    try:
        return callbacks.resolve_callback(card_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown callback card")


class ImportRequest(BaseModel):
    kind: str  # conflicts | faqs | matters
    csv_text: str
    dry_run: bool = True


@app.post("/import")
def import_data(req: ImportRequest) -> dict:
    """Bonus Part 2: the importer. Dry-run (default) only previews;
    dry_run=false writes the clean, new rows."""
    try:
        if req.dry_run:
            return importer.preview_import(req.kind, req.csv_text)
        return importer.apply_import(req.kind, req.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
