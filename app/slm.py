import re

from pydantic import ValidationError

from . import ollama_client
from .prompts import ANALYSE_SYSTEM
from .schemas import Flag, NoteAnalysis


def _tidy(text: str) -> str:
    # lower case, and one space between words, so small differences do not matter
    return re.sub(r"\s+", " ", text).strip().lower()


def evidence_in_note(evidence: str, note: str) -> bool:
    """True only if the AI's evidence really appears in the carer's note."""
    return bool(_tidy(evidence)) and _tidy(evidence) in _tidy(note)


def analyse_note(note: str) -> tuple[NoteAnalysis, list[Flag]]:
    """Ask the small model for a summary and flags.

    Returns (analysis with only proven flags, flags that were dropped).
    """
    raw = ollama_client.chat_json(
        ANALYSE_SYSTEM,
        f"Carer's note:\n{note}",
        NoteAnalysis.model_json_schema(),
    )

    try:
        result = NoteAnalysis.model_validate_json(raw)
    except ValidationError as error:
        raise ollama_client.OllamaError(
            "The model gave an answer we could not read. Please try again."
        ) from error

    kept: list[Flag] = []
    dropped: list[Flag] = []
    seen_types: set[str] = set()

    for flag in result.flags:
        if not evidence_in_note(flag.evidence, note):
            dropped.append(flag)  # the AI made this up, so a nurse never sees it
        elif flag.type not in seen_types:  # one flag per type is enough
            kept.append(flag)
            seen_types.add(flag.type)

    return NoteAnalysis(summary=result.summary.strip(), flags=kept), dropped
