"""FastAPI front door. For now: a health check. The intake endpoints land in later parts."""

from fastapi import FastAPI

app = FastAPI(title="LexIntake")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "lexintake"}
