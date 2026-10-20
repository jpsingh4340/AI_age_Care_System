import json
import math
import re
from pathlib import Path

from . import ollama_client
from .prompts import PLAN_CHECK_SYSTEM
from .schemas import PlanCheckOut, PlanCheckResult
from .slm import evidence_in_note

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "care_plans.json"

# The search index is built once, the first time we need it, then kept in memory.
_index: list[dict] | None = None


def load_chunks() -> list[dict]:
    """Cut the fake care plans and home procedures into small pieces (chunks)."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    chunks = []
    for plan in data["care_plans"]:
        for text in plan["items"]:
            chunks.append(
                {
                    "resident_id": plan["resident_id"],
                    "source": f"Care plan for {plan['resident']}",
                    "text": text,
                }
            )
    for text in data["home_procedures"]:
        chunks.append({"resident_id": None, "source": "Rest home procedure", "text": text})
    return chunks


def build_index() -> list[dict]:
    """Turn every chunk into numbers (a vector) so we can search by meaning."""
    global _index
    chunks = load_chunks()
    vectors = ollama_client.embed([chunk["text"] for chunk in chunks])
    _index = [{**chunk, "vector": vector} for chunk, vector in zip(chunks, vectors)]
    return _index


def _cosine(a: list[float], b: list[float]) -> float:
    """How similar two vectors are: 1 = same meaning, 0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def retrieve(resident_id: int, note: str, k: int = 5) -> list[dict]:
    """Find the k care plan or procedure lines most related to the note.

    Only this resident's lines and the shared home procedures are searched,
    so one resident's plan never leaks into another resident's summary.
    """
    index = _index if _index is not None else build_index()

    # Compare each sentence of the note with each chunk, and keep the best match.
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", note.strip()) if s] or [note]
    sentence_vectors = ollama_client.embed(sentences)

    candidates = [c for c in index if c["resident_id"] in (resident_id, None)]
    scored = []
    for chunk in candidates:
        score = max(_cosine(vec, chunk["vector"]) for vec in sentence_vectors)
        scored.append({"source": chunk["source"], "text": chunk["text"], "score": round(score, 3)})

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:k]


def check_plan(resident_id: int, note: str) -> tuple[list[PlanCheckOut], list[dict]]:
    """RAG: retrieve the relevant lines, then ask the small model to compare."""
    retrieved = retrieve(resident_id, note)
    numbered = "\n".join(f"{i}. {item['text']}" for i, item in enumerate(retrieved, start=1))

    raw = ollama_client.chat_json(
        PLAN_CHECK_SYSTEM,
        f"Care plan lines:\n{numbered}\n\nCarer's note:\n{note}",
        PlanCheckResult.model_json_schema(),
    )
    try:
        result = PlanCheckResult.model_validate_json(raw)
    except Exception as error:
        raise ollama_client.OllamaError(
            "The model gave an answer we could not read. Please try again."
        ) from error

    checks: list[PlanCheckOut] = []
    done: set[int] = set()
    for check in result.checks:
        if not 1 <= check.item_number <= len(retrieved) or check.item_number in done:
            continue  # ignore made-up or repeated line numbers
        done.add(check.item_number)

        status = check.status
        evidence = check.note_evidence.strip()
        # "met" and "off_plan" need proof from the note, otherwise we say "unclear"
        if status in ("met", "off_plan") and not evidence_in_note(evidence, note):
            status, evidence = "unclear", ""

        item = retrieved[check.item_number - 1]
        checks.append(
            PlanCheckOut(
                plan_item=item["text"],
                source=item["source"],
                status=status,
                note_evidence=evidence,
            )
        )
    return checks, retrieved
