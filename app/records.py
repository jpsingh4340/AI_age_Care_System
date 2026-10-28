"""Fake resident records for the doctor summary (Feature B).

Everything here is made-up data in data/records.json. Nothing is written by an AI.
"""
import json
from pathlib import Path

from . import db, guidance
from .schemas import RecordsOut

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _records_for(resident_id: int) -> dict | None:
    data = json.loads((DATA_DIR / "records.json").read_text(encoding="utf-8"))
    for record in data["residents"]:
        if record["resident_id"] == resident_id:
            return record
    return None


def _care_plan_for(resident_id: int) -> list[str]:
    data = json.loads((DATA_DIR / "care_plans.json").read_text(encoding="utf-8"))
    for plan in data["care_plans"]:
        if plan["resident_id"] == resident_id:
            return plan["items"]
    return []


import sqlite3


def _live_carer_entries(resident_id: int) -> tuple[list[dict], list[dict]]:
    """Load real shift tasks and concerns recorded by carers from the database."""
    db_path = getattr(db, "DB_PATH", DATA_DIR / "agecare.db")
    if not Path(db_path).exists():
        return [], []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tasks: list[dict] = []
    concerns: list[dict] = []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT task, status, carer, created_at FROM carer_tasks WHERE resident_id = ? ORDER BY created_at ASC",
            (str(resident_id),),
        )
        for r in cur.fetchall():
            tasks.append({
                "time": r["created_at"][11:16] if len(r["created_at"]) >= 16 else r["created_at"],
                "task": r["task"],
                "status": r["status"] if r["status"] in ("given", "refused", "not_done") else "given",
                "by": r["carer"],
            })

        cur.execute(
            "SELECT type, note, carer, created_at FROM carer_concerns WHERE resident_id = ? ORDER BY created_at ASC",
            (str(resident_id),),
        )
        for r in cur.fetchall():
            concerns.append({
                "time": r["created_at"][11:16] if len(r["created_at"]) >= 16 else r["created_at"],
                "type": r["type"],
                "text": f"{r['note']} (reported by {r['carer']})",
            })
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return tasks, concerns


def build_records(resident_id: int) -> RecordsOut | None:
    """Everything the doctor PDF needs about one resident, or None if there is no such resident."""
    resident = guidance.load_resident(resident_id)
    record = _records_for(resident_id)
    if resident is None or record is None:
        return None
    
    live_tasks, live_concerns = _live_carer_entries(resident_id)
    merged_care = list(record["care_record"]) + live_tasks
    merged_concerns = list(record["concerns"]) + live_concerns

    return RecordsOut(
        resident_id=resident_id,
        name=resident["name"],
        conditions=[c["name"] for c in resident["conditions"]],
        allergies=record["allergies"],
        doctor=record["doctor"],
        contacts=record["contacts"],
        care_plan=_care_plan_for(resident_id),
        care_record=merged_care,
        concerns=merged_concerns,
        readings_history=record["readings_history"],
        readings_saved=db.list_readings(resident_id),
    )