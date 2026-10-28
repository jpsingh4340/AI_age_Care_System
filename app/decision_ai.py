"""AI layer for the Care Priority Decision feature (written by Tanveer).

The small language model (Ollama, running on our own laptop) reads the carer
notes for ONE resident and points out worries, copying the exact words.
The AI only explains: my code checks every answer before a nurse sees it.

Safety rules in this file:
1. A quote that is not really in a carer note is removed (the AI made it up).
2. A reason that mentions a medicine, a dose or a diagnosis is removed.
3. The AI can only give Green or Amber. Only the NZEWS rules can give Red.
"""
from pydantic import BaseModel, ValidationError

from . import ollama_client
from .decision_rules import AMBER, GREEN, highest_level
from .guidance import contains_blocked
from .schemas import FlagType
from .slm import evidence_in_note

# My prompt: the instructions we give the small model. Short, strict rules work
# best for small models. (Version 1 - see the prompt log in docs/decision-research.md)
DECISION_NOTE_SYSTEM = """You help a nurse in a New Zealand rest home decide which carer notes need a nurse to check.
You get the carer notes about ONE resident. Each note starts with its time in brackets.

Rules:
- Use ONLY the carer notes. Do not add facts.
- Add a concern only when a note clearly says something worrying happened, for example not eating or drinking, a fall or near fall, pain, vomiting, confusion or low mood.
- If a note says something did NOT happen (for example "no falls today"), do not add it.
- "quote" must be words copied exactly from one note, 3 to 15 words long.
- "reason" is one short sentence in plain English that tells the nurse why it may need checking.
- "needs_check" is true when a nurse should check the resident, and false when it is only for information.
- Never diagnose. Never name medicines, doses or treatment.
- If nothing is worrying, return an empty concerns list.
- Concern types you may use: Not eating, Low fluids, Fall risk, Mobility, Pain, Vomiting, Poor sleep, Mood, Other.
"""


# The shape the AI's answer must have (Ollama is forced to follow it).
class NoteConcern(BaseModel):
    type: FlagType
    quote: str
    reason: str
    needs_check: bool


class NoteConcerns(BaseModel):
    concerns: list[NoteConcern]


def read_notes(notes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Ask the AI about the carer notes, then keep only answers that pass my checks.

    notes looks like [{"time": "10:20", "text": "Nearly slipped when getting out of the chair."}]
    Returns (kept concerns, dropped concerns). Each kept concern has a level and a source.
    """
    if not notes:
        return [], []  # nothing to read, so we do not call the AI

    notes_text = "\n".join(f"[{note['time']}] {note['text']}" for note in notes)
    raw = ollama_client.chat_json(
        DECISION_NOTE_SYSTEM,
        f"Carer notes:\n{notes_text}",
        NoteConcerns.model_json_schema(),
    )
    try:
        answer = NoteConcerns.model_validate_json(raw)
    except ValidationError as error:
        raise ollama_client.OllamaError(
            "The model gave an answer we could not read. Please try again."
        ) from error

    kept, dropped, seen_types = [], [], set()
    for concern in answer.concerns:
        # 1. Find the note the quote came from. No note means the AI made it up.
        note = next((n for n in notes if evidence_in_note(concern.quote, n["text"])), None)
        if note is None:
            dropped.append({**concern.model_dump(), "why": "The quote is not in any carer note."})
            continue
        # 2. Never show a medicine, dose or diagnosis.
        if contains_blocked(concern.reason):
            dropped.append({**concern.model_dump(), "why": "It mentions a medicine, dose or diagnosis."})
            continue
        # 3. One concern of each type is enough.
        if concern.type in seen_types:
            continue
        seen_types.add(concern.type)

        kept.append({
            "type": concern.type,
            "quote": concern.quote.strip(),
            "reason": concern.reason.strip(),
            "level": AMBER if concern.needs_check else GREEN,  # never Red
            "source": f"Carer note, {note['time']}",
        })
    return kept, dropped


def notes_level(concerns: list[dict]) -> str:
    """One level from the carer notes. It can only be Green or Amber."""
    return highest_level([concern["level"] for concern in concerns])
