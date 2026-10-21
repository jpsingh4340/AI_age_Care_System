"""Feature A: nurse-approved symptoms to watch for and prevention.

The AI may only rewrite lines from approved sources. Every line it writes is
checked automatically. A line that fails a check is removed and recorded.
A nurse approval step comes next, so everything here is still a DRAFT.
"""
import json
import re
from pathlib import Path

from . import ollama_client
from .prompts import GUIDANCE_SYSTEM
from .schemas import (
    CheckedLine,
    DroppedLine,
    GuidanceDraft,
    GuidanceLine,
    SourceOut,
)
from .slm import evidence_in_note

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MAX_LINE_LENGTH = 220  # characters
MIN_GROUNDED = 0.5  # at least half of the line's words must appear in its source

# Words and patterns the AI must never produce. A nurse is the last safety net,
# but we stop the obvious ones before the nurse sees them.
DOSE_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s?(mg|mcg|µg|ml|g|units?|tablets?|capsules?|drops?)\b", re.IGNORECASE
)
BLOCKED_WORDS = re.compile(
    r"\b(paracetamol|panadol|ibuprofen|aspirin|morphine|codeine|insulin|warfarin|"
    r"antibiotics?|painkillers?|medication|medicine|medicines|prescri\w*|dose|doses|"
    r"diagnos\w*)\b",
    re.IGNORECASE,
)

def contains_blocked(text: str) -> bool:
    """True if the text mentions a medicine, a dose or a diagnosis."""
    return bool(DOSE_PATTERN.search(text) or BLOCKED_WORDS.search(text))

def _read(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def load_resident(resident_id: int) -> dict | None:
    for resident in _read("residents.json")["residents"]:
        if resident["resident_id"] == resident_id:
            return resident
    return None

def list_residents() -> list[dict]:
    """The fake residents, with their recorded conditions, for the screen's drop-down."""
    return [
        {
            "resident_id": r["resident_id"],
            "name": r["name"],
            "conditions": [c["name"] for c in r["conditions"]],
        }
        for r in _read("residents.json")["residents"]
    ]

def build_sources(resident: dict) -> list[SourceOut]:
    """Collect the approved lines this resident's guidance may use.

    1. The resident's own care plan.
    2. The reference notes for the topics of their recorded conditions.
    """
    sources: list[SourceOut] = []

    def add(label: str, text: str) -> None:
        sources.append(SourceOut(id=f"S{len(sources) + 1}", source=label, text=text))

    for plan in _read("care_plans.json")["care_plans"]:
        if plan["resident_id"] == resident["resident_id"]:
            for text in plan["items"]:
                add(f"Care plan for {plan['resident']}", text)

    topics = {condition["topic"] for condition in resident["conditions"]}
    for note in _read("reference_notes.json")["notes"]:
        if note["topic"] in topics:
            for text in note["lines"]:
                add(f"Reference note: {note['title']}", text)
    return sources


def _stems(text: str) -> set[str]:
    # first five letters of each word of 4+ letters, so "drink" matches "drinks"
    return {word[:5] for word in re.findall(r"[a-z]{4,}", text.lower())}


def check_line(line: GuidanceLine, by_id: dict[str, SourceOut]) -> str | None:
    """Return why the line must be removed, or None if it passes every check."""
    source = by_id.get(line.source_id.strip())
    if source is None:
        return "The source number does not exist."
    if not evidence_in_note(line.quote, source.text):
        return "The quote is not in the cited source."
    if contains_blocked(line.text):
        return "Mentions a medicine, dose or diagnosis."
    if len(line.text) > MAX_LINE_LENGTH or not line.text.strip():
        return "The line is empty or too long."
    words = _stems(line.text)
    if words and len(words & _stems(source.text)) / len(words) < MIN_GROUNDED:
        return "Too many words that are not in the cited source."
    return None

def _limited_schema() -> dict:
    """The answer shape we send to Ollama, with size limits so the model cannot ramble."""
    schema = GuidanceDraft.model_json_schema()
    for name in ("watch_for", "prevention"):
        schema["properties"][name]["minItems"] = 2
        schema["properties"][name]["maxItems"] = 4
    line = schema["$defs"]["GuidanceLine"]["properties"]
    line["text"]["maxLength"] = MAX_LINE_LENGTH
    line["quote"]["maxLength"] = 160
    line["source_id"]["maxLength"] = 6
    return schema


def draft_guidance(resident_id: int):
    """Ask the small model for guidance, then keep only the lines that pass every check.

    Returns (resident, sources, watch_for, prevention, dropped), or None if the resident
    does not exist.
    """
    resident = load_resident(resident_id)
    if resident is None:
        return None

    sources = build_sources(resident)
    by_id = {source.id: source for source in sources}

    listing = "\n".join(f"{s.id} ({s.source}): {s.text}" for s in sources)
    conditions = ", ".join(c["name"] for c in resident["conditions"])
    raw = ollama_client.chat_json(
        GUIDANCE_SYSTEM,
        f"Resident: {resident['name']}\nRecorded conditions: {conditions}\n\nSources:\n{listing}\n\nNow write the two lists for this resident.",
        _limited_schema(),
 )
    try:
        draft = GuidanceDraft.model_validate_json(raw)
    except Exception as error:
        raise ollama_client.OllamaError(
            "The model gave an answer we could not read. Please try again."
        ) from error

    kept = {"watch_for": [], "prevention": []}
    dropped: list[DroppedLine] = []
    seen: set[str] = set()

    for list_name in ("watch_for", "prevention"):
        for line in getattr(draft, list_name)[:8]:  # never trust a huge answer
            reason = check_line(line, by_id)
            key = re.sub(r"\s+", " ", line.text).strip().lower()
            if reason is None and key in seen:
                reason = "Duplicate line."
            if reason:
                dropped.append(
                    DroppedLine(
                        list_name=list_name,
                        text=line.text,
                        source_id=line.source_id,
                        quote=line.quote,
                        reason=reason,
                    )
                )
                continue
            seen.add(key)
            kept[list_name].append(
                CheckedLine(
                    text=line.text.strip(),
                    source_id=line.source_id.strip(),
                    source=by_id[line.source_id.strip()].source,
                    quote=line.quote.strip(),
                )
            )

    return resident, sources, kept["watch_for"], kept["prevention"], dropped
