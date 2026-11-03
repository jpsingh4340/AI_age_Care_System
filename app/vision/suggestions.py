"""Feature C: suggested next steps for the nurse when an alert comes in.

Fixed safe first steps for the alert type, plus the lines from the resident's
care plan and the home's procedures that match the alert.

The nurse decides. These are prompts, not instructions.
"""
import json

from app import guidance

# Safe first steps we wrote ourselves, per alert type. No diagnosis, no medicine.
FIRST_STEPS = {
    "possible_fall": [
        "Go to the resident now and stay with them.",
        "Do not lift them until a nurse has checked them for injury.",
        "Ask if they hurt anywhere, and write down the time and what you saw.",
    ],
    "no_movement": [
        "Go to the resident now and call their name.",
        "Check they respond and are breathing normally.",
        "If they are asleep and comfortable, help them change position if the care plan says so.",
    ],
    "high_cue": [
        "Go to the resident soon and ask how they feel.",
        "Ask if anything hurts, and where. Write down their own words.",
        "Check comfort: position, toilet, a drink, warm enough.",
    ],
    "medium_cue": [
        "Check in with the resident when you can and ask how they feel.",
        "Offer comfort: a drink, a change of position, the toilet.",
        "Write down what you saw and heard.",
    ],
}

# Words that make a care-plan line relevant to each alert type.
KEYWORDS = {
    "possible_fall": ["fall", "frame", "stand", "reach", "slip", "trip", "walk"],
    "no_movement": ["reposition", "position", "drink", "fluid", "sleep"],
    "high_cue": ["pain", "sick", "feel", "drink", "position", "vomit"],
    "medium_cue": ["pain", "sick", "feel", "drink", "position", "enjoys", "phone"],
}


def _care_plan_lines(alert_type, resident_id):
    data = json.loads((guidance.DATA_DIR / "care_plans.json").read_text(encoding="utf-8"))
    words = KEYWORDS.get(alert_type, [])
    lines = []
    for plan in data["care_plans"]:
        if plan["resident_id"] == resident_id:
            for text in plan["items"]:
                if any(w in text.lower() for w in words):
                    lines.append({"text": text, "source": f"Care plan for {plan['resident']}"})
    for text in data["home_procedures"]:
        if any(w in text.lower() for w in words):
            lines.append({"text": text, "source": "Home procedure"})
    return lines


def for_alert(alert):
    """Level 1: safe first steps plus matching care-plan lines. Instant, no AI."""
    first = [{"text": t, "source": "Feature C first steps"} for t in FIRST_STEPS.get(alert["alert_type"], [])]
    return {"method": "care plan", "steps": first + _care_plan_lines(alert["alert_type"], alert["resident_id"])}

