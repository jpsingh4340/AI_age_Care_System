"""Patient / Resident Portal page and API.

Empowers aged-care residents with:
- Accessible schedule & daily routine (synced with carer tasks)
- One-tap daily wellbeing check-in (auto-alerts nurse/carer on discomfort)
- Digital Bedside Call Bell for immediate assistance
- Plain-language nurse-approved care instructions
"""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app import auth, config, db, guidance
from app.schemas import (
    PatientCallBellRequest,
    PatientCompanionRequest,
    PatientCompanionResponse,
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


EMERGENCY_KEYWORDS = [
    "fall", "fell", "floor", "drop", "chest pain", "cannot breathe",
    "can't breathe", "severe pain", "emergency", "hurt bad", "bleeding"
]


def _clean_speech_text(text: str) -> str:
    cleaned = re.sub(r"[\*\_#>`~\[\]\(\)]", "", text)
    cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@router.post("/api/patient/companion", response_model=PatientCompanionResponse)
async def post_companion(
    body: PatientCompanionRequest,
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Empathetic AI Bedside Voice Companion for elderly residents."""
    res_id = _get_resident_id_from_auth(authorization, x_session_token, resident_id or body.resident_id)
    resident = guidance.load_resident(res_id)
    name = resident["name"] if resident else f"Resident #{res_id}"
    first_name = name.split()[0]
    room_number = f"Room {100 + res_id}"
    query = body.question.strip()
    q_lower = query.lower()

    # 1. Safety check: emergency, severe distress, or falls
    is_emergency = any(kw in q_lower for kw in EMERGENCY_KEYWORDS)
    if is_emergency:
        alert_msg = f"AI Voice Companion Emergency: Resident asked '{query}'"
        auth.trigger_call_bell(res_id, name, alert_msg)
        reply = (
            f"Dear {first_name}, please stay still and do not try to get up. "
            f"I have alerted Nurse Sarah and your carer right now to come to your room immediately. Help is on the way."
        )
        return PatientCompanionResponse(
            reply=reply,
            speech_text=_clean_speech_text(reply),
            emergency_alert=True,
            suggested_followups=["Nurse is notified", "Stay comfortable", "Help is coming"],
        )

    # 2. Gather context: schedule & approved nurse guidance
    today_prefix = datetime.now().date().isoformat() + "%"
    completed = []
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            "SELECT task, status, carer, created_at FROM carer_tasks WHERE resident_id = ? AND created_at LIKE ?",
            (str(res_id), today_prefix),
        )
        for r in cur.fetchall():
            time_str = r["created_at"][11:16] if len(r["created_at"]) >= 16 else ""
            completed.append(f"- {r['task']} was completed at {time_str} by carer {r['carer']}")
        con.close()
    except Exception:
        pass

    completed_context = "\n".join(completed) if completed else "No tasks recorded yet today."

    guidance_notes = []
    approved = db.latest_approved(res_id)
    if approved:
        for p in approved.get("prevention", []):
            guidance_notes.append(p.get("text", ""))
    guidance_context = "; ".join(guidance_notes[:3]) if guidance_notes else "General mobility with frame and hydration support."

    schedule_lines = [f"{item['time']} - {item['title']}" for item in ROUTINE_SCHEDULE]
    schedule_context = "\n".join(schedule_lines)

    system_prompt = (
        f"You are Grace, an empathetic, caring bedside AI voice companion for an elderly resident named {name} ({room_number}). "
        f"Always answer in an extremely warm, comforting, and simple tone (maximum 2 to 3 short sentences). "
        f"Never use medical jargon or complex words. Never prescribe medication or diagnose illnesses. "
        f"Today's resident schedule:\n{schedule_context}\n"
        f"Carer visits recorded today:\n{completed_context}\n"
        f"Care plan notes:\n{guidance_context}\n"
        f"If {first_name} asks where they are or feels confused, warmly reassure them that they are safe in their cozy room at AgeCare Haven. "
        f"If {first_name} asks about meals or daily activities, answer clearly using the schedule."
    )

    ollama_url = getattr(config, "OLLAMA_URL", "http://127.0.0.1:11434")
    model = getattr(config, "CHAT_MODEL", "llama3.2:3b")

    reply = ""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 120},
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("message", {}).get("content", "").strip()
    except Exception:
        pass

    # Safe clinical fallback if Ollama is offline or slow
    if not reply:
        if any(w in q_lower for w in ["lunch", "dinner", "breakfast", "food", "eat", "hungry", "meal"]):
            reply = f"Your next meal is Lunch at 12:30 PM in the dining lounge, and dinner is served at 5:30 PM. Would you like a warm cup of tea now, {first_name}?"
        elif any(w in q_lower for w in ["walk", "frame", "physio", "exercise", "move", "outside"]):
            reply = f"Your daily mobility walk with your frame is scheduled for 11:30 AM. Your carer will be here to walk alongside you safely."
        elif any(w in q_lower for w in ["carer", "nurse", "visit", "who"]):
            reply = f"Your care team is on duty right down the hall. Carer Priya is looking after your wing today, and Nurse Sarah is on clinical oversight."
        elif any(w in q_lower for w in ["where", "home", "time", "confused", "place"]):
            reply = f"You are safe and sound in your cozy room 101 at AgeCare Haven, {first_name}. Everything is peaceful, and we are right here with you."
        else:
            reply = f"Hello {first_name}! You are having a peaceful day today. Lunch is at 12:30 PM, and your carer will be visiting you shortly. How can I brighten your day?"

    return PatientCompanionResponse(
        reply=reply,
        speech_text=_clean_speech_text(reply),
        emergency_alert=False,
        suggested_followups=[
            "What is for lunch?",
            "When is my walk?",
            "Who is my carer today?",
            "Can I have a cup of tea?",
        ],
    )
