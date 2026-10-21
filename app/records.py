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


def build_records(resident_id: int) -> RecordsOut | None:
    """Everything the doctor PDF needs about one resident, or None if there is no such resident."""
    resident = guidance.load_resident(resident_id)
    record = _records_for(resident_id)
    if resident is None or record is None:
        return None
    return RecordsOut(
        resident_id=resident_id,
        name=resident["name"],
        conditions=[c["name"] for c in resident["conditions"]],
        allergies=record["allergies"],
        doctor=record["doctor"],
        contacts=record["contacts"],
        care_plan=_care_plan_for(resident_id),
        care_record=record["care_record"],
        concerns=record["concerns"],
        readings_history=record["readings_history"],
        readings_saved=db.list_readings(resident_id),
    )