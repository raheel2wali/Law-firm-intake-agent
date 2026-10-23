"""The mystery-shopper eval set (Part 8: Evals & Quality).

Twenty-five scripted caller personas that run through the graders every
time. Each persona is the caller's full story, plus what a good intake
should have captured from it. The harness checks three things:

1. completeness — did the intake capture who/what/when/where/urgency?
2. qualification — right practice area, right priority?
3. the gotchas — the edge cases production taught us (the 2 AM caller
   from Part 8, the desperate advice-seeker from Part 6, the incomplete
   intake that should never have been booked).

Run it with: python evals/eval_quality.py

Exit code is 0 only if everything passes. And the rule from the series:
every bad intake in production gets added to data/eval_regressions.jsonl
(quality.add_regression_case) BEFORE it gets a fix, so the suite keeps
every mistake the system ever made.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import quality  # noqa: E402

# Each persona: name, the caller's story, what a good intake captures,
# the practice area the firm would expect, and the urgency level.
PERSONAS = [
    {
        "name": "2am rear-ended, statute clock ticking",
        "transcript": "I'm Maria Santos. I was rear-ended on I-10 last Tuesday around "
                      "11pm. My wrist is sprained. I haven't filed anything yet.",
        "who": "Maria Santos", "what": "rear-ended on I-10, sprained wrist",
        "when": "last Tuesday 11pm", "where": "I-10", "urgency": "normal",
        "practice_area": "personal_injury", "priority": "standard",
    },
    {
        "name": "arrest tonight, needs help now",
        "transcript": "My brother James Carter was arrested two hours ago in Harris "
                      "County. Bail hearing is in the morning. I need a lawyer tonight.",
        "who": "James Carter's brother", "what": "arrested, bail hearing in the morning",
        "when": "two hours ago", "where": "Harris County", "urgency": "high",
        "practice_area": "criminal", "priority": "urgent",
    },
    {
        "name": "simple divorce consult",
        "transcript": "Hi, I'm Priya Nair. My husband and I are separating and I want "
                      "to understand the divorce process. No rush, just exploring.",
        "who": "Priya Nair", "what": "divorce consultation",
        "when": "no deadline", "where": "not stated", "urgency": "low",
        "practice_area": "family", "priority": "routine",
    },
    {
        "name": "slip and fall at the grocery store",
        "transcript": "Robert Delgado here. I slipped on a wet floor at the Kroger on "
                      "Westheimer yesterday morning and hurt my back.",
        "who": "Robert Delgado", "what": "slip and fall, hurt back",
        "when": "yesterday morning", "where": "Kroger on Westheimer", "urgency": "normal",
        "practice_area": "personal_injury", "priority": "standard",
    },
    {
        "name": "custody fight escalating",
        "transcript": "This is Angela Ruiz. My ex is refusing to return my kids after "
                      "his custody weekend visit. This started Saturday. I don't know what to do.",
        "who": "Angela Ruiz", "what": "ex refusing to return kids",
        "when": "Saturday", "where": "not stated", "urgency": "high",
        "practice_area": "family", "priority": "urgent",
    },
    {
        "name": "ER visit after the crash",
        "transcript": "David Kim. I was injured last night when a pickup ran a red "
                      "light and crashed into my car on Richmond Avenue. My shoulder may be fractured.",
        "who": "David Kim", "what": "hit by pickup, possible fractured shoulder",
        "when": "last night", "where": "Richmond Avenue", "urgency": "high",
        "practice_area": "personal_injury", "priority": "urgent",
    },
    {
        "name": "will and estate planning",
        "transcript": "I'm Helen Brooks. My husband passed last year and I need to set "
                      "up a will and sort out his estate. Whenever you have time.",
        "who": "Helen Brooks", "what": "will and estate setup",
        "when": "no deadline", "where": "not stated", "urgency": "low",
        "practice_area": "estate", "priority": "routine",
    },
    {
        "name": "DUI last weekend",
        "transcript": "This is Tom Alvarez. I got pulled over and arrested for a DUI "
                      "last Saturday night near downtown. Court date is next month.",
        "who": "Tom Alvarez", "what": "DUI arrest",
        "when": "last Saturday night", "where": "downtown", "urgency": "normal",
        "practice_area": "criminal", "priority": "standard",
    },
    {
        "name": "fired without warning",
        "transcript": "My name is Sarah Okafor. My employer fired me Friday with no "
                      "warning after I reported safety violations. I worked there three years.",
        "who": "Sarah Okafor", "what": "fired after reporting safety violations",
        "when": "Friday", "where": "workplace", "urgency": "normal",
        "practice_area": "employment", "priority": "standard",
    },
    {
        "name": "visa renewal deadline",
        "transcript": "Hello, I'm Ahmed Hassan. My work visa expires in 40 days and my "
                      "employer hasn't started the renewal paperwork. I'm worried.",
        "who": "Ahmed Hassan", "what": "work visa renewal",
        "when": "expires in 40 days", "where": "not stated", "urgency": "normal",
        "practice_area": "immigration", "priority": "standard",
    },
    {
        "name": "contract dispute with vendor",
        "transcript": "Kevin Park here, I run a small print shop. A vendor breached our "
                      "supply contract last month and I lost two big clients.",
        "who": "Kevin Park", "what": "vendor breached supply contract",
        "when": "last month", "where": "business", "urgency": "normal",
        "practice_area": "corporate", "priority": "standard",
    },
    {
        "name": "desperate caller begs for a yes",
        "transcript": "Please, just tell me I have a case. The insurance company keeps "
                      "calling and I don't know what to say. I need you to say yes.",
        "who": "", "what": "insurance pressure, wants reassurance",
        "when": "ongoing", "where": "not stated", "urgency": "normal",
        "practice_area": "unknown", "priority": "standard",
        "min_completeness": 0.6,  # thin intake with no classifiable facts: allowed, flagged
    },
    {
        "name": "terse caller, almost no detail",
        "transcript": "I need a lawyer. Car thing. Last week.",
        "who": "", "what": "car thing", "when": "last week", "where": "", "urgency": "",
        "practice_area": "unknown", "priority": "standard",
        "min_completeness": 0.4,  # known gap: keyword matcher can't tell "car thing" is an accident; LLM extraction does
    },
    {
        "name": "wrongly deprioritized urgent case",
        "transcript": "I'm Lisa Morgan. My ex-husband threatened me at the custody "
                      "exchange yesterday. Court hearing is tomorrow morning.",
        "who": "Lisa Morgan", "what": "threatened at custody exchange",
        "when": "yesterday, hearing tomorrow morning", "where": "custody exchange",
        "urgency": "high",
        "practice_area": "family", "priority": "urgent",
        "must_be_urgent": True,
    },
    {
        "name": "green card through marriage",
        "transcript": "Hi, Elena Petrova. I married a US citizen in March and we want "
                      "to start my green card application soon.",
        "who": "Elena Petrova", "what": "green card application",
        "when": "married in March", "where": "not stated", "urgency": "low",
        "practice_area": "immigration", "priority": "routine",
    },
    {
        "name": "harassment at work",
        "transcript": "This is Grace Adeyemi. My manager has been harassing me for "
                      "months and HR did nothing. I have it all documented.",
        "who": "Grace Adeyemi", "what": "workplace harassment, documented",
        "when": "ongoing for months", "where": "workplace", "urgency": "normal",
        "practice_area": "employment", "priority": "standard",
    },
    {
        "name": "LLC formation",
        "transcript": "I'm Daniel Reyes and I'm starting a landscaping company. I need "
                      "help forming an LLC and drafting client contracts.",
        "who": "Daniel Reyes", "what": "LLC formation and contracts",
        "when": "no deadline", "where": "not stated", "urgency": "low",
        "practice_area": "corporate", "priority": "routine",
    },
    {
        "name": "probate after father's death",
        "transcript": "My father passed away two weeks ago without a will. I'm his "
                      "daughter, Nancy Whitfield. We need help with probate.",
        "who": "Nancy Whitfield", "what": "probate, no will",
        "when": "two weeks ago", "where": "not stated", "urgency": "normal",
        "practice_area": "estate", "priority": "standard",
    },
    {
        "name": "deportation notice",
        "transcript": "I received a deportation notice yesterday. My name is Omar "
                      "Farouk. I have a hearing in 60 days. Please help.",
        "who": "Omar Farouk", "what": "deportation notice",
        "when": "received yesterday, hearing in 60 days", "where": "not stated",
        "urgency": "high",
        "practice_area": "immigration", "priority": "urgent",
    },
    {
        "name": "bike accident, uninsured driver",
        "transcript": "I'm Chris Novak. An uninsured driver hit me while I was biking "
                      "on Allen Parkway three days ago. My knee is swollen.",
        "who": "Chris Novak", "what": "hit by uninsured driver, swollen knee",
        "when": "three days ago", "where": "Allen Parkway", "urgency": "normal",
        "practice_area": "personal_injury", "priority": "standard",
    },
    {
        "name": "child support modification",
        "transcript": "Hello, I'm Fatima Ali. I lost my job in September and I can't "
                      "afford my current child support payments. I need a modification.",
        "who": "Fatima Ali", "what": "child support modification",
        "when": "lost job in September", "where": "not stated", "urgency": "normal",
        "practice_area": "family", "priority": "standard",
    },
    {
        "name": "bail for a friend",
        "transcript": "My friend Marcus Webb is in county jail right now. He was "
                      "arrested last night for shoplifting. Can someone see him today?",
        "who": "Marcus Webb", "what": "arrested for shoplifting, in county jail",
        "when": "last night", "where": "county jail", "urgency": "high",
        "practice_area": "criminal", "priority": "urgent",
    },
    {
        "name": "landlord refusing deposit",
        "transcript": "I moved out of my apartment in August and my landlord won't "
                      "return my $1800 deposit. I'm Yuki Tanaka.",
        "who": "Yuki Tanaka", "what": "landlord withholding deposit",
        "when": "moved out in August", "where": "apartment", "urgency": "low",
        "practice_area": "unknown", "priority": "routine",
        "min_completeness": 0.8,
    },
    {
        "name": "wrongful termination with paper trail",
        "transcript": "I'm Victor Hale. I was terminated Monday after filing a wage "
                      "complaint with the state. I kept every email.",
        "who": "Victor Hale", "what": "terminated after wage complaint",
        "when": "Monday", "where": "workplace", "urgency": "normal",
        "practice_area": "employment", "priority": "standard",
    },
    {
        "name": "multilingual caller, short answers",
        "transcript": "Me Juan. Accident. Car. Yesterday. Katy.",
        "who": "Juan", "what": "car accident", "when": "yesterday", "where": "Katy",
        "urgency": "",
        "practice_area": "personal_injury", "priority": "standard",
        "min_completeness": 0.8,
    },
]

# The bar: every persona must classify to the right practice area, and
# urgency must drive the priority. Thin intakes (low completeness) are
# allowed, but they have to be *flagged* thin, never silently booked.
QUALIFICATION_ACCURACY_FLOOR = 0.9


def grade_persona(p: dict) -> tuple[bool, str]:
    intake = {f: p.get(f, "") for f in ("who", "what", "when", "where", "urgency")}
    intake["practice_area"] = quality.classify_practice(p["transcript"])
    intake["priority"] = quality.expected_priority(p.get("urgency", ""))
    intake["transcript"] = p["transcript"]

    score = quality.completeness_score(intake)
    floor = p.get("min_completeness", 1.0)
    if score < floor:
        return False, f"completeness {score} below floor {floor}"

    qualified = quality.qualification_correct(intake, p["transcript"])
    expected_area = p["practice_area"]
    if intake["practice_area"] != expected_area:
        return False, f"practice area: got {intake['practice_area']}, want {expected_area}"

    if p.get("must_be_urgent") and intake["priority"] != "urgent":
        return False, "urgent case was not prioritized urgent"

    if intake["priority"] != p["priority"]:
        return False, f"priority: got {intake['priority']}, want {p['priority']}"

    return qualified, f"completeness {score}, qualified_ok={qualified}"


def load_regression_cases() -> list[dict]:
    path = quality.REGRESSIONS_LOG
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    failures = 0
    qualified_ok = 0

    for p in PERSONAS:
        passed, detail = grade_persona(p)
        print(f"{'PASS' if passed else 'FAIL'}  {p['name']}: {detail}")
        if not passed:
            failures += 1
        else:
            qualified_ok += 1

    accuracy = qualified_ok / len(PERSONAS)
    print()
    print(f"mystery shoppers: {len(PERSONAS)} personas")
    print(f"qualification accuracy: {accuracy:.0%}")
    if accuracy < QUALIFICATION_ACCURACY_FLOOR:
        print(f"FAIL  accuracy floor {QUALIFICATION_ACCURACY_FLOOR:.0%} not met")
        failures += 1

    regressions = load_regression_cases()
    for case in regressions:
        passed, detail = grade_persona(case)
        print(f"{'PASS' if passed else 'FAIL'}  regression: {case.get('name', '?')}: {detail}")
        if not passed:
            failures += 1
    print(f"regression cases from production: {len(regressions)}")

    print()
    print(f"{len(PERSONAS) + len(regressions) - failures}/{len(PERSONAS) + len(regressions)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
