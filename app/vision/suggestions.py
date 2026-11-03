"""Feature C: suggested next steps for the nurse when an alert comes in.

Two levels:
  1. Always: fixed safe first steps for the alert type, plus the lines from the
     resident's care plan and the home's procedures that match the alert.
  2. On request: the local AI (Ollama) turns those same lines into a short,
     ordered plan. It may only use the lines it is given, every step must name
     its source, and any step that mentions a medicine, a dose or a diagnosis
     is removed. If Ollama is not running, the nurse still gets level 1.

The nurse decides. These are prompts, not instructions.
"""
import json
import re

from app import guidance, ollama_client
from app.config import CHAT_MODEL

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

AI_SYSTEM = (
    "You help an aged-care nurse decide what to do after an alert. "
    "Use ONLY the numbered lines you are given. Write 2 to 4 short steps in plain words, "
    "most urgent first. Each step must give the id of the line it comes from. "
    "Never name or guess a disease or a cause. Never mention a medicine or a dose."
)
AI_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "source": {"type": "string"}},
                "required": ["text", "source"],
            },
        }
    },
    "required": ["steps"],
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


def ai_for_alert(alert):
    """Level 2: the local AI orders and words the same lines. Falls back to level 1."""
    base = for_alert(alert)
    numbered = {f"L{i + 1}": s for i, s in enumerate(base["steps"])}
    prompt = f"Alert: {alert['message']}\n\nLines you may use:\n" + "\n".join(
        f"{key}: {s['text']} ({s['source']})" for key, s in numbered.items()
    )
    try:
        raw = ollama_client.chat_json(AI_SYSTEM, prompt, AI_SCHEMA)
        steps = json.loads(raw).get("steps", [])
    except (ollama_client.OllamaError, ValueError) as error:
        return {**base, "note": f"AI not available, showing the care plan instead. {error}"}

    kept, dropped = [], {"no source": 0, "too long": 0, "unsafe": 0}
    for step in steps:
         if isinstance(step, str):  # small models sometimes send plain text
            step = {"text": step, "source": ""}
         text = re.sub(r"^\s*L?\d+\s*[:.)-]\s*", "", str(step.get("text", ""))).strip()  # drop a copied "L1:" label
         source = numbered.get(_line_id(step.get("source", ""), text, numbered))
         if not text:
            continue
         if source is None:
            dropped["no source"] += 1
         elif len(text) > 300:
            dropped["too long"] += 1
         elif guidance.contains_blocked(text):
            dropped["unsafe"] += 1
         else:
            kept.append({"text": text, "source": source["source"]})
    removed = ", ".join(f"{n} {why}" for why, n in dropped.items() if n)
    if not kept:
        why = f" Removed: {removed}." if removed else ""
        return {**base, "note": f"The AI answer did not pass the safety checks, showing the care plan instead.{why}"}
    result = {"method": "ai", "model": CHAT_MODEL, "steps": kept[:4]}
    if removed:
        result["note"] = f"Some AI steps were removed by the safety checks ({removed})."
    return result


def _line_id(source, text, numbered):
    """Find which line a step came from. Small models write "L2", "2", "Line 2" or copy the line itself."""
    match = re.search(r"(\d+)", str(source))
    if match and f"L{match.group(1)}" in numbered:
        return f"L{match.group(1)}"
    for key, line in numbered.items():  # no usable id: accept it if it repeats a given line
        if line["text"].lower()[:40] in text.lower() or text.lower()[:40] in line["text"].lower():
            return key
    return None
