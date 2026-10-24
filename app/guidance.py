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

    def add(label: str, text: str, topic: str = "") -> None:
        sources.append(SourceOut(id=f"S{len(sources) + 1}", source=label, text=text, topic=topic))

    for plan in _read("care_plans.json")["care_plans"]:
        if plan["resident_id"] == resident["resident_id"]:
            for text in plan["items"]:
                add(f"Care plan for {plan['resident']}", text)

    topics = {condition["topic"] for condition in resident["conditions"]}
    for note in _read("reference_notes.json")["notes"]:
        if note["topic"] in topics:
            for text in note["lines"]:
                add(f"Reference note: {note['title']}", text, note["topic"])
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

def _limited_schema(smallest: int = 2, largest: int = 4) -> dict:
    """The answer shape we send to Ollama, with size limits so the model cannot ramble."""
    schema = GuidanceDraft.model_json_schema()
    for name in ("watch_for", "prevention"):
        schema["properties"][name]["minItems"] = smallest
        schema["properties"][name]["maxItems"] = largest
    line = schema["$defs"]["GuidanceLine"]["properties"]
    line["text"]["maxLength"] = MAX_LINE_LENGTH
    line["quote"]["maxLength"] = 160
    line["source_id"]["maxLength"] = 6
    return schema


def _ask_model(resident: dict, sources: list[SourceOut], schema: dict, extra: str = "") -> GuidanceDraft:
    """One call to the small model. Returns its answer, not yet checked."""
    listing = "\n".join(f"{s.id} ({s.source}): {s.text}" for s in sources)
    conditions = ", ".join(c["name"] for c in resident["conditions"])
    raw = ollama_client.chat_json(
        GUIDANCE_SYSTEM,
        f"Resident: {resident['name']}\nRecorded conditions: {conditions}\n\n{extra}Sources:\n{listing}\n\nNow write the two lists for this resident.",
        schema,
    )
    try:
        return GuidanceDraft.model_validate_json(raw)
    except Exception as error:
        raise ollama_client.OllamaError(
            "The model gave an answer we could not read. Please try again."
        ) from error


LIST_LABELS = {"watch_for": "symptoms to watch for", "prevention": "prevention steps"}
NEAR_DUPLICATE = 0.75  # two lines sharing this much of their words count as the same line


def _too_similar(text: str, kept: dict) -> bool:
    """True if this line says almost the same as a line we already kept."""
    words = _stems(text)
    for name in kept:
        for other in kept[name]:
            theirs = _stems(other.text)
            union = words | theirs
            if union and len(words & theirs) / len(union) >= NEAR_DUPLICATE:
                return True
    return False


def _keep_checked_lines(draft: GuidanceDraft, by_id: dict[str, SourceOut], kept: dict, dropped: list, seen: set) -> None:
    """Run every automatic check. Lines that pass go into `kept`, the rest into `dropped`."""
    for list_name in ("watch_for", "prevention"):
        for line in getattr(draft, list_name)[:8]:  # never trust a huge answer
            reason = check_line(line, by_id)
            key = re.sub(r"\s+", " ", line.text).strip().lower()
            if reason is None and key in seen:
                reason = "Duplicate line."
            elif reason is None and _too_similar(line.text, kept):
                reason = "Almost the same as another line."
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


def uncovered(resident: dict, sources: list[SourceOut], kept: dict) -> list[tuple[str, str]]:
    """What is still missing: each recorded condition needs a kept line in BOTH lists.

    Returns (topic, list_name) pairs, in condition order.
    """
    topic_of = {s.id: s.topic for s in sources}
    missing: list[tuple[str, str]] = []
    for condition in resident["conditions"]:
        topic = condition["topic"]
        for list_name in ("watch_for", "prevention"):
            has_line = any(topic_of.get(line.source_id) == topic for line in kept[list_name])
            if not has_line and (topic, list_name) not in missing:
                missing.append((topic, list_name))
    return missing


def _title_of(sources: list[SourceOut], topic: str) -> str:
    for source in sources:
        if source.topic == topic:
            return source.source.replace("Reference note: ", "")
    return topic


def _gap_names(sources: list[SourceOut], missing: list[tuple[str, str]]) -> list[str]:
    return [f"{_title_of(sources, topic)} ({LIST_LABELS[list_name]})" for topic, list_name in missing]


def draft_guidance(resident_id: int):
    """Ask the small model for guidance, then keep only the lines that pass every check.

    Each recorded condition should have at least one kept line in both lists. If something
    is missing, ask once more using only the sources for those conditions. Anything still
    missing is returned as `gaps`, so the nurse knows to add a line herself.

    Returns (resident, sources, watch_for, prevention, dropped, gaps), or None if the
    resident does not exist.
    """
    resident = load_resident(resident_id)
    if resident is None:
        return None

    sources = build_sources(resident)
    by_id = {source.id: source for source in sources}
    kept: dict[str, list[CheckedLine]] = {"watch_for": [], "prevention": []}
    dropped: list[DroppedLine] = []
    seen: set[str] = set()

    _keep_checked_lines(_ask_model(resident, sources, _limited_schema()), by_id, kept, dropped, seen)

    missing = uncovered(resident, sources, kept)
    if missing:
        topics = {topic for topic, _ in missing}
        wanted = [s for s in sources if s.topic in topics]
        note = (
            "Your first answer left out: " + ", ".join(_gap_names(sources, missing))
            + ". This time write lines ONLY from the sources below.\n\n"
        )
        try:
            more = _ask_model(resident, wanted, _limited_schema(1, 3), note)
            _keep_checked_lines(more, {s.id: s for s in wanted}, kept, dropped, seen)
        except ollama_client.OllamaError:
            pass  # keep the first answer. The gaps are shown to the nurse instead.
        missing = uncovered(resident, sources, kept)

    return resident, sources, kept["watch_for"], kept["prevention"], dropped, _gap_names(sources, missing)