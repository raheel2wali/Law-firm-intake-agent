"""Settings. Fails fast if the API key is missing."""

import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Copy .env.example to .env and fill it in."
    )

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
