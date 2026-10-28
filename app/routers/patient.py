"""Patient / Resident Portal page and API.

Empowers aged-care residents with:
- Accessible schedule & daily routine (synced with carer tasks)
- One-tap daily wellbeing check-in (auto-alerts nurse/carer on discomfort)
- Digital Bedside Call Bell for immediate assistance
- Plain-language nurse-approved care instructions
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app import auth, db, guidance
from app.schemas import (
    PatientCallBellRequest,
    PatientDayResponse,
    PatientScheduleItem,
    PatientWellbeingRequest,
)

router = APIRouter(tags=["Patient / Resident Portal"])

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "static"
DB_PATH = getattr(db, "DB_PATH", BASE_DIR / "data" / "agecare.db")

ROUTINE_SCHEDULE = [
    {"time": "08:00", "title": "Breakfast & Morning Refresh", "task_match": "Breakfast eaten"},
    {"time": "10:00", "title": "Morning Hydration & Tea", "task_match": "Offer a drink"},
    {"time": "11:30", "title": "Mobility Walk / Physiotherapy", "task_match": "Walk with frame"},
    {"time": "12:30", "title": "Lunch in Dining Lounge", "task_match": "Lunch eaten"},
    {"time": "14:30", "title": "Rest & Repositioning", "task_match": "Help to change position"},
    {"time": "17:30", "title": "Dinner Service", "task_match": "Dinner eaten"},
]


def _get_resident_id_from_auth(
    authorization: str = "",
    x_session_token: str = "",
    resident_id: int | None = None,
) -> int:
    """Resolve resident ID from session token or query."""
    token = x_session_token.strip() if x_session_token else ""
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    if token:
        sess = auth.get_session(token)
        if sess and sess.get("resident_id"):
            return int(sess["resident_id"])

    return int(resident_id or 1)


@router.get("/patient", include_in_schema=False)
def patient_page():
    """The resident tablet interface."""
    return FileResponse(STATIC_DIR / "patient.html")


@router.get("/api/patient/my-day", response_model=PatientDayResponse)
def get_patient_day(
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Retrieve resident's daily schedule, synced carer completed tasks, and approved guidance."""
    res_id = _get_resident_id_from_auth(authorization, x_session_token, resident_id)
    resident = guidance.load_resident(res_id)
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found.")

    # 1. Fetch completed tasks from carer_tasks for today
    today_prefix = datetime.now().date().isoformat() + "%"
    completed_tasks: dict[str, dict] = {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS carer_tasks (
                id INTEGER PRIMARY KEY, resident_id TEXT, task TEXT, status TEXT,
                carer TEXT, created_at TEXT)"""
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT task, status, carer, created_at FROM carer_tasks WHERE resident_id = ? AND created_at LIKE ? ORDER BY created_at DESC",
            (str(res_id), today_prefix),
        )
        for r in cur.fetchall():
            task_name = r["task"]
            if task_name not in completed_tasks:
                completed_tasks[task_name] = {
                    "status": r["status"],
                    "by": r["carer"],
                    "time": r["created_at"][11:16] if len(r["created_at"]) >= 16 else "",
                }
    except sqlite3.OperationalError:
        pass

    # 2. Latest wellbeing check-in
    latest_sentiment = None
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS patient_wellbeing (
                id INTEGER PRIMARY KEY, resident_id INTEGER NOT NULL, sentiment TEXT NOT NULL,
                note TEXT, created_at TEXT NOT NULL)"""
        )
        cur.execute(
            "SELECT sentiment FROM patient_wellbeing WHERE resident_id = ? AND created_at LIKE ? ORDER BY id DESC LIMIT 1",
            (res_id, today_prefix),
        )
        row = cur.fetchone()
        if row:
            latest_sentiment = row["sentiment"]
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    # 3. Assemble schedule items
    schedule: list[PatientScheduleItem] = []
    for item in ROUTINE_SCHEDULE:
        match = completed_tasks.get(item["task_match"])
        if match:
            status_text = f"Completed ({match['status']})" if match["status"] != "given" else "✓ Completed"
            carer_text = f"Assisted by {match['by']}"
        else:
            status_text = "Scheduled"
            carer_text = None

        schedule.append(
            PatientScheduleItem(
                time=item["time"],
                title=item["title"],
                status=status_text,
                completed_by=carer_text,
            )
        )

    # 4. Plain-language approved guidance from nurse
    approved_lines = []
    approved = db.latest_approved(res_id)
    if approved:
        for p in approved.get("prevention", []):
            approved_lines.append(p["text"])
        for w in approved.get("watch_for", []):
            approved_lines.append(w["text"])

    room_number = f"Room {100 + res_id}"

    return PatientDayResponse(
        resident_id=res_id,
        name=resident["name"],
        room=room_number,
        schedule=schedule,
        approved_guidance=approved_lines[:5],
        latest_sentiment=latest_sentiment,
    )


@router.post("/api/patient/wellbeing")
def post_wellbeing(
    body: PatientWellbeingRequest,
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Save patient 1-tap feeling check-in. Auto-alerts nurse and carer if uncomfortable."""
    res_id = _get_resident_id_from_auth(authorization, x_session_token, resident_id)
    return auth.log_patient_wellbeing(res_id, body.sentiment, body.note)


@router.post("/api/patient/call-bell")
def post_call_bell(
    body: PatientCallBellRequest,
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Trigger digital call bell for immediate help."""
    res_id = _get_resident_id_from_auth(authorization, x_session_token, resident_id)
    resident = guidance.load_resident(res_id)
    res_name = resident["name"] if resident else f"Resident #{res_id}"
    return auth.trigger_call_bell(res_id, res_name, body.request_type)
