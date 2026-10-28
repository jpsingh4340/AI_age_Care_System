"""Care Priority Decision: puts the rules and the AI together (written by Tanveer).

For one resident:
1. Collect the vital signs and carer notes (fake records + entries from the carer page).
2. Rules (NZEWS) check the vital signs        -> Green, Amber or Red.
3. The AI reads the carer notes               -> Green or Amber (never Red).
4. The most serious level wins, and every reason keeps its source.
5. A nurse accepts or changes it, and that is saved in the audit log.
"""
import time

from . import db, decision_ai, ollama_client, records
from .decision_rules import AMBER, GREEN, RED, check_vitals, highest_level, rules_level, total_score
from .routers import carer

NEXT_STEP = {
    RED: "A nurse should see the resident now.",
    AMBER: "A nurse should check the resident.",
    GREEN: "Continue normal care.",
}

# The AI is slow on a laptop, so we remember its answer for the same notes.
_ai_memory: dict[tuple, tuple] = {}


def _carer_page_entries(resident_id: int) -> tuple[dict, list[dict]]:
    """Vital signs and concerns that carers saved on the carer page (if any)."""
    extra_vitals: dict[str, list[dict]] = {}
    notes: list[dict] = []
    try:
        con = carer.get_db()
        vitals = con.execute(
            "SELECT * FROM carer_vitals WHERE resident_id = ? ORDER BY id", (str(resident_id),)
        ).fetchall()
        concerns = con.execute(
            "SELECT * FROM carer_concerns WHERE resident_id = ? ORDER BY id", (str(resident_id),)
        ).fetchall()
        con.close()
    except Exception:  # the carer tables may not exist yet
        return extra_vitals, notes

    for row in vitals:
        for key in ("pulse", "systolic", "temperature", "spo2"):
            if row[key] is not None:
                extra_vitals.setdefault(key, []).append({"date": row["created_at"], "value": row[key]})
    for row in concerns:
        notes.append({"time": row["created_at"][11:16], "text": row["note"]})
    return extra_vitals, notes


def _read_notes_with_ai(notes: list[dict]) -> tuple[list[dict], list[dict], float]:
    key = tuple((n["time"], n["text"]) for n in notes)
    if key not in _ai_memory:
        start = time.perf_counter()
        kept, dropped = decision_ai.read_notes(notes)
        _ai_memory[key] = (kept, dropped, round(time.perf_counter() - start, 1))
    return _ai_memory[key]


def build_decision(resident_id: int, use_ai: bool = True) -> dict | None:
    """The priority for one resident, with every reason and its source. None if not found."""
    record = records.build_records(resident_id)
    if record is None:
        return None

    # 1. Collect the data
    history = {key: [point.model_dump() for point in values]
               for key, values in record.readings_history.items()}
    extra_vitals, carer_notes = _carer_page_entries(resident_id)
    for key, values in extra_vitals.items():
        history.setdefault(key, []).extend(values)
    notes = [{"time": c.time, "text": c.text} for c in record.concerns] + carer_notes

    # 2. Rules
    vitals = check_vitals(history)
    rules = rules_level(vitals)

    # 3. AI (if it is switched on and Ollama is running)
    concerns, dropped, seconds = [], [], 0.0
    ai_status, ai_message = "off", "The AI was not used."
    if use_ai and notes:
        try:
            concerns, dropped, seconds = _read_notes_with_ai(notes)
            ai_status, ai_message = "ok", f"The AI read {len(notes)} carer note(s) in {seconds} seconds."
        except ollama_client.OllamaError as error:
            ai_status, ai_message = "error", f"{error} The priority below uses the vital signs only."
    elif use_ai:
        ai_status, ai_message = "ok", "There are no carer notes to read."

    # 4. Combine: the most serious level wins
    level = highest_level([rules] + [c["level"] for c in concerns])
    reasons = [
        {"level": v["level"], "text": v["reason"], "source": v["source"], "from": "rules"}
        for v in vitals if v["level"] != GREEN
    ] + [
        {"level": c["level"], "text": f"{c['type']}: {c['reason']}", "quote": c["quote"],
         "source": c["source"], "from": "ai"}
        for c in concerns
    ]
    reasons.sort(key=lambda r: {RED: 0, AMBER: 1, GREEN: 2}[r["level"]])

    return {
        "resident_id": resident_id,
        "name": record.name,
        "level": level,
        "next_step": NEXT_STEP[level],
        "rules": {"level": rules, "nzews_total": total_score(vitals), "vitals": vitals},
        "ai": {"status": ai_status, "message": ai_message, "level": decision_ai.notes_level(concerns),
               "removed_by_check": len(dropped)},
        "reasons": reasons,
        "last_review": latest_review(resident_id),
    }


# ---------- the nurse's decision ----------
def save_review(resident_id: int, reviewer: str, suggested: str, final: str, note: str) -> dict:
    """Save the nurse's decision in the audit log."""
    if final == suggested:
        action, detail = "priority_accepted", f"Accepted the suggested priority {suggested}."
    else:
        action, detail = "priority_changed", f"Changed the priority from {suggested} to {final}. Reason: {note}"
    with db.session() as conn:
        db._audit(conn, reviewer, "nurse", action, resident_id, None, detail)
    return latest_review(resident_id)


def latest_review(resident_id: int) -> dict | None:
    """The last time a nurse accepted or changed this resident's priority."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE resident_id = ? AND action IN "
            "('priority_accepted', 'priority_changed') ORDER BY id DESC LIMIT 1",
            (resident_id,),
        ).fetchone()
    return dict(row) if row else None