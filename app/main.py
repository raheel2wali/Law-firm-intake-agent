"""FastAPI front door: a health check, the confirmation endpoint that
approves the agent's proposed writes (Part 5: The Hands), and the voice
webhook that feeds phone calls into the intake pipeline (Part 7)."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import tools, voice
from app.tools import IntegrationNotWired, ScopeDenied

app = FastAPI(title="LexIntake")


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
