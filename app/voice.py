"""Part 7: The Voice Channel.

Most intakes start as phone calls, so LexIntake meets the caller there:
after-hours answering plus a missed-call text-back during business hours.
Both feed the same interview pipeline from Parts 1-6, so qualification,
the conflict check, and the ethics guardrails ride along for free.

The actual telephony stays where it belongs, with the provider. This
module only handles the boring glue: normalized payload in, a decision
out. Nothing here rings a phone or sends a real SMS; the adapters for
that land with the real integrations in Part 9.
"""

from datetime import datetime

from app.intake import Intake, run_turn
from app.guardrails import guard_turn, redact_pii, with_disclaimer

AFTER_HOURS_GREETING = (
    "Thanks for calling. I'm an intake assistant, not an attorney. "
    "I can take down the details of your case and have someone call you back."
)

TEXT_BACK_TEMPLATE = (
    "Hi, sorry we missed your call. This is {firm_name}. "
    "Tell me briefly what this is about and I'll have someone get back to you."
)


def parse_call_payload(payload: dict) -> dict:
    """Normalize a provider webhook payload into something we can reason
    about. Shaped for Twilio-style fields; other providers map the same way."""
    return {
        "call_id": payload.get("CallSid", "unknown"),
        "from": payload.get("From", "unknown"),
        "to": payload.get("To", "unknown"),
        "status": payload.get("CallStatus", "unknown"),
        "answered": payload.get("AnsweredBy") == "human",
        "transcript": payload.get("TranscriptionText", ""),
    }


def handle_missed_call(payload: dict, firm_name: str = "the firm") -> dict:
    """A call came in, rang out, and the firm didn't pick up. Don't log a
    voicemail for Monday; text back within the minute and open an intake."""
    call = parse_call_payload(payload)
    message = TEXT_BACK_TEMPLATE.format(firm_name=firm_name)
    # The transcript is empty (nobody picked up), but the phone number and
    # timestamp are the seed for an intake the moment the caller replies.
    intake = Intake()
    return {
        "call_id": call["call_id"],
        "action": "text_back",
        "to": call["from"],
        "message": message,
        "at": datetime.utcnow().isoformat(),
        "note": "caller reply continues the same interview loop via /voice",
    }


def run_transcript(call_from: str, segments: list[str]) -> dict:
    """Feed spoken turns through the interview pipeline. Each segment is one
    transcribed caller utterance. Returns every assistant reply plus the
    intake card the attorney gets in the morning."""
    intake = Intake()
    replies: list[str] = []

    for segment in segments:
        # The ethics guardrails run first, same as on chat. The caller on a
        # shaky midnight phone call is exactly who might ask "do I have a
        # case"; the refusal policy doesn't care which channel it came in on.
        verdict = guard_turn(segment)
        if verdict.get("action") != "ok":
            replies.append(with_disclaimer(verdict["message"]))
            continue
        result = run_turn(intake, segment)
        if result["action"] == "decline":
            replies.append(result["message"])
            return {"action": "decline", "replies": replies,
                    "alert": result["alert"]}
        if result["action"] == "book":
            replies.append(with_disclaimer(
                "That's everything I need. I'll have an attorney call you back."))
            return {"action": "book", "replies": replies,
                    "summary": redact_pii(result["summary"])}
        replies.append(with_disclaimer(result["question"]))

    # Caller ran out of things to say before the facts were complete.
    # Hand over what's known; a half-filled card beats a lost caller.
    return {"action": "partial", "replies": replies,
            "summary": redact_pii(intake.summary())}


def handle_voice_call(payload: dict) -> dict:
    """After-hours call answered by the agent. Greet, listen, and run the
    transcript through the intake pipeline."""
    call = parse_call_payload(payload)
    segments = [s.strip() for s in call["transcript"].split("\n") if s.strip()]
    if not segments:
        return {"call_id": call["call_id"], "action": "no_audio",
                "greeting": with_disclaimer(AFTER_HOURS_GREETING),
                "note": "no transcription available; fall back to missed-call text-back"}
    outcome = run_transcript(call["from"], segments)
    outcome["call_id"] = call["call_id"]
    outcome["greeting"] = with_disclaimer(AFTER_HOURS_GREETING)
    return outcome
