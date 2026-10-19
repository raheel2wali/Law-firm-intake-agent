"""FastAPI front door: a health check, plus the confirmation endpoint
that approves the agent's proposed writes (Part 5: The Hands)."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import tools
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
