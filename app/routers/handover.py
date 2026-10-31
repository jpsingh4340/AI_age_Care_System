# Carer to nurse handover workflow.
#
#   carer   writes quick notes during the shift and ticks off the nurse's care plan
#   carer   asks the AI to draft an ISBAR handover for the shift, edits it, and sends it to the nurse
#   nurse   reads the draft next to the carer's source notes, edits it, then approves it or sends it back
#   nurse   keeps a care plan for each resident (every day, or chosen days of the week)
#   nurse   drafts a family update from an approved handover, then sends it with the family update API
#   nurse and family   message each other about one resident; urgent family messages are flagged
#
# Shifts: AM 07:00 to 15:00, PM 15:00 to 23:00, Night 23:00 to 07:00.
# Every endpoint checks the signed-in user's session and role on the server.
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import auth, guidance, ollama_client
from app.config import CHAT_MODEL
from app.prompts import FAMILY_FROM_HANDOVER_SYSTEM, HANDOVER_SYSTEM
from app.routers import carer, portal

router = APIRouter(tags=["Handover"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
STATUS_TEXT = {"given": "done", "refused": "refused", "not_done": "not done"}

SHIFTS = (("AM", 7), ("PM", 15), ("Night", 23))  # name, start hour; each shift is 8 hours
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ISBAR_FIELDS = ("situation", "background", "assessment", "recommendation")
REPLY_HOURS = (8, 20)  # nurses usually answer family messages between 8 am and 8 pm

# Families should not see clinical readings or scores, only plain words.
CLINICAL_FOR_FAMILY = re.compile(
    r"\b(spo2|sp02|oxygen|saturation|pulse|heart rate|blood pressure|bp|temperature|temp|nzews|ews|"
    r"mmhg|bpm|vital signs?|score)\b|\d+\s?(%|°)",
    re.IGNORECASE,
)

# Words in a family message that a nurse should see straight away.
URGENT_FAMILY = re.compile(
    r"\b(fall|fell|fallen|pain|painful|hurt|hurting|bleed\w*|blood|chest|breath\w*|unconscious|collaps\w*|"
    r"emergency|ambulance|hospital|chok\w*|seizure|suicid\w*|urgent|asap|worried|scared)\b",
    re.IGNORECASE,
)

MEDICINE_WORDS = re.compile(r"\b(medicine|medicines|medication|meds|tablets?|pills?|insulin|inhaler|eye drops)\b", re.IGNORECASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS carer_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    carer TEXT NOT NULL,
    carer_user TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS care_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    task TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS schedule_done (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    done_by TEXT NOT NULL,
    done_at TEXT NOT NULL,
    UNIQUE (schedule_id, day)
);
CREATE TABLE IF NOT EXISTS handovers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    carer TEXT NOT NULL,
    carer_user TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | waiting | approved | returned
    ai_text TEXT NOT NULL,                  -- what the AI (or the rules) wrote
    text TEXT NOT NULL,                     -- the current wording
    drafted_by TEXT NOT NULL,               -- 'AI' or 'Rules'
    sources TEXT NOT NULL,                  -- JSON: the carer records the draft was made from
    since TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    family_update_id INTEGER
);
"""

# Columns added after the first version of these tables
MIGRATIONS = {
    "care_schedule": [
        ("days", "TEXT NOT NULL DEFAULT ''"),        # '' = every day, else e.g. 'mon,wed,fri'
        ("medicine", "INTEGER NOT NULL DEFAULT 0"),  # a medicine round: only medication-competent staff tick it
    ],
    "handovers": [("shift_key", "TEXT NOT NULL DEFAULT ''"), ("shift_label", "TEXT NOT NULL DEFAULT ''")],
    "family_messages": [("sender_role", "TEXT NOT NULL DEFAULT 'family'")],
}


# ---------- helpers ----------
def get_db() -> sqlite3.Connection:
    con = portal.get_db()  # also creates the family tables
    con.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    con.commit()
    return con


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().date().isoformat()


def signed_in(roles: tuple[str, ...], authorization: str, x_session_token: str) -> dict:
    return portal.require(roles, authorization, x_session_token)


def own_resident_only(sess: dict, resident_id: int) -> None:
    """Family accounts can only reach their own family member."""
    if sess["role"] == "family" and sess.get("resident_id") != resident_id:
        raise HTTPException(403, "You can only see messages about your own family member.")


# ---------- shifts ----------
def shift_at(moment: datetime) -> dict:
    """The shift that `moment` falls in."""
    hour = moment.hour
    if 7 <= hour < 15:
        name, start = "AM", datetime.combine(moment.date(), time(7))
    elif 15 <= hour < 23:
        name, start = "PM", datetime.combine(moment.date(), time(15))
    else:
        name = "Night"
        start_day = moment.date() if hour >= 23 else moment.date() - timedelta(days=1)
        start = datetime.combine(start_day, time(23))
    end = start + timedelta(hours=8)
    label = f"{name} shift, {start.strftime('%a')} {start.day} {start.strftime('%b')}, {start:%H:%M} to {end:%H:%M}"
    return {
        "key": f"{start.date().isoformat()}-{name}",
        "name": name,
        "label": label,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }


def shifts_now(moment: datetime | None = None) -> dict:
    """The current and previous shift. In the first hour of a shift we suggest the previous one,
    so a carer finishing a little late still hands over the shift they worked."""
    moment = moment or datetime.now()
    current = shift_at(moment)
    previous = shift_at(datetime.fromisoformat(current["start"]) - timedelta(seconds=1))
    early = moment - datetime.fromisoformat(current["start"]) < timedelta(hours=1)
    return {"current": current, "previous": previous, "suggested": "previous" if early else "current"}


# ---------- care plan ----------
def applies_on(item: dict, day: date) -> bool:
    days = [d for d in (item.get("days") or "").split(",") if d]
    return not days or DAYS[day.weekday()] in days


def schedule_rows(con: sqlite3.Connection, resident_id: int, day: date | None = None, every: bool = False) -> list[dict]:
    """Care plan items with who ticked them off on `day` (today by default).
    Only items planned for that day, unless `every` is True."""
    day = day or datetime.now().date()
    rows = con.execute(
        "SELECT s.*, d.done_by, d.done_at FROM care_schedule s "
        "LEFT JOIN schedule_done d ON d.schedule_id = s.id AND d.day = ? "
        "WHERE s.resident_id = ? AND s.active = 1 "
        "ORDER BY CASE WHEN s.time = '' THEN 1 ELSE 0 END, s.time, s.id",
        (day.isoformat(), resident_id),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["medicine"] = bool(item["medicine"])
        item["days"] = [d for d in item["days"].split(",") if d]
        item["planned_today"] = applies_on(dict(r), day)
        if every or item["planned_today"]:
            out.append(item)
    return out


def item_in_shift(item: dict, day: date, shift: dict) -> bool:
    """Timed items belong to the shift their time falls in. Untimed items belong to the day shifts."""
    start, end = datetime.fromisoformat(shift["start"]), datetime.fromisoformat(shift["end"])
    if item["time"]:
        at = datetime.combine(day, time.fromisoformat(item["time"]))
        return start <= at < end
    return shift["name"] in ("AM", "PM") and day == start.date()


# ---------- shift records ----------
def outside_range(v: sqlite3.Row) -> bool:
    """Same simple check as the carer page. Not a risk score."""
    return bool(
        (v["pulse"] is not None and not 50 <= v["pulse"] <= 100)
        or (v["temperature"] is not None and not 36.0 <= v["temperature"] <= 37.8)
        or (v["spo2"] is not None and v["spo2"] < 94)
        or (v["systolic"] is not None and not 100 <= v["systolic"] <= 160)
    )


def vitals_text(v: sqlite3.Row) -> str:
    parts = []
    if v["pulse"] is not None:
        parts.append(f"pulse {v['pulse']}")
    if v["systolic"] is not None and v["diastolic"] is not None:
        parts.append(f"BP {v['systolic']}/{v['diastolic']}")
    if v["temperature"] is not None:
        parts.append(f"temp {v['temperature']}°C")
    if v["spo2"] is not None:
        parts.append(f"SpO2 {v['spo2']}%")
    text = "Vital signs: " + ", ".join(parts)
    return text + (" (outside usual range)" if outside_range(v) else "")


def handover_window(con: sqlite3.Connection, resident_id: int, shift: dict) -> str:
    """Records from the start of the shift, or after a handover already sent for this shift."""
    row = con.execute(
        "SELECT MAX(sent_at) FROM handovers WHERE resident_id = ? AND shift_key = ? AND status IN ('waiting', 'approved')",
        (resident_id, shift["key"]),
    ).fetchone()
    if row[0]:
        return (datetime.fromisoformat(row[0]) + timedelta(seconds=1)).isoformat(timespec="seconds")
    return shift["start"]


def shift_sources(resident_id: int, since: str, shift: dict) -> dict:
    """Everything carers recorded for one resident from `since` to the end of the shift,
    oldest first, plus care plan items for this shift that are not done."""
    until = shift["end"]
    entries = []
    rid = str(resident_id)
    con = carer.get_db()
    try:
        window = (rid, since, until)
        for r in con.execute("SELECT * FROM carer_tasks WHERE resident_id = ? AND created_at >= ? AND created_at < ?", window):
            entries.append({"at": r["created_at"], "kind": "Task", "text": f"{r['task']}: {STATUS_TEXT.get(r['status'], r['status'])}", "by": r["carer"]})
        for r in con.execute("SELECT * FROM carer_vitals WHERE resident_id = ? AND created_at >= ? AND created_at < ?", window):
            entries.append({"at": r["created_at"], "kind": "Vital signs", "text": vitals_text(r), "by": r["carer"]})
        for r in con.execute("SELECT * FROM carer_concerns WHERE resident_id = ? AND created_at >= ? AND created_at < ?", window):
            entries.append({"at": r["created_at"], "kind": "Concern", "text": f"{r['type']}: {r['note']}", "by": r["carer"]})
    finally:
        con.close()

    con = get_db()
    try:
        for r in con.execute(
            "SELECT * FROM carer_notes WHERE resident_id = ? AND created_at >= ? AND created_at < ?",
            (resident_id, since, until),
        ):
            entries.append({"at": r["created_at"], "kind": "Note", "text": r["text"], "by": r["carer"]})
        for r in con.execute(
            "SELECT s.task, d.done_by, d.done_at FROM schedule_done d JOIN care_schedule s ON s.id = d.schedule_id "
            "WHERE s.resident_id = ? AND d.done_at >= ? AND d.done_at < ?",
            (resident_id, since, until),
        ):
            entries.append({"at": r["done_at"], "kind": "Care plan", "text": f"{r['task']}: done", "by": r["done_by"]})

        not_done = []
        start, end = datetime.fromisoformat(shift["start"]), datetime.fromisoformat(shift["end"])
        for day in sorted({start.date(), (end - timedelta(seconds=1)).date()}):
            for item in schedule_rows(con, resident_id, day):
                if item_in_shift(item, day, shift) and not item["done_at"]:
                    not_done.append(((item["time"] + " ") if item["time"] else "") + item["task"])
    finally:
        con.close()

    entries.sort(key=lambda e: e["at"])
    return {"entries": entries, "not_done": not_done}


# ---------- AI drafting ----------
def new_unsafe_words(text: str, source: str) -> bool:
    """True if the AI added a medicine, dose or diagnosis word that the carer never wrote."""
    lower = source.lower()
    words = {w.lower() for w in guidance.BLOCKED_WORDS.findall(text)}
    if any(w not in lower for w in words):
        return True
    return any(m.group(0).lower() not in lower for m in guidance.DOSE_PATTERN.finditer(text))


def ask_model(system: str, user: str, fields: tuple[str, ...] = ("text",)) -> dict:
    """Ask the local model and force a JSON answer with these string fields."""
    schema = {"type": "object", "properties": {f: {"type": "string"} for f in fields}, "required": list(fields)}
    data = ollama_client._post(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.2, "num_predict": 420, "num_gpu": ollama_client.NUM_GPU},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=120,
    )
    answer = json.loads(data["message"]["content"])
    return {f: str(answer.get(f, "")).strip() for f in fields}


def isbar_text(identify: str, parts: dict) -> str:
    return "\n".join(
        [f"Identify: {identify}"] + [f"{field.capitalize()}: {parts[field]}" for field in ISBAR_FIELDS]
    )


def rules_isbar(person: dict, src: dict) -> dict:
    """Used when the AI is not available, or wrote something unsafe."""
    first = person["name"].split(" ")[0]
    entries = src["entries"]
    concerns = [e["text"] for e in entries if e["kind"] == "Concern"]
    flagged = [e["text"] for e in entries if e["kind"] == "Vital signs" and "outside usual range" in e["text"]]
    other_vitals = [e["text"] for e in entries if e["kind"] == "Vital signs" and "outside usual range" not in e["text"]]
    care = [e["text"] for e in entries if e["kind"] in ("Task", "Care plan")]
    notes = [e["text"].rstrip(".") + "." for e in entries if e["kind"] == "Note"]
    conditions = ", ".join(c["name"] for c in person.get("conditions", [])) or "none recorded"

    situation = " ".join(
        ([("Concerns: " + "; ".join(concerns) + ".")] if concerns else [])
        + ([("Outside usual range: " + "; ".join(flagged) + ".")] if flagged else [])
    ) or ("No concerns recorded this shift." if entries else f"Nothing was recorded for {first} this shift.")
    assessment = " ".join(
        ([("Care: " + "; ".join(care) + ".")] if care else [])
        + ([("Carer notes: " + " ".join(notes))] if notes else [])
        + ([("; ".join(other_vitals) + ".")] if other_vitals else [])
    ) or "No care or notes recorded."
    asks = []
    if concerns or flagged:
        asks.append("Please check the concerns above.")
    if src["not_done"]:
        asks.append("Still to do: " + ", ".join(src["not_done"]) + ".")
    return {
        "situation": situation,
        "background": f"Recorded conditions: {conditions}.",
        "assessment": assessment,
        "recommendation": " ".join(asks) or "Continue the usual care plan.",
    }


def draft_handover_text(person: dict, src: dict, shift: dict, carer_name: str) -> tuple[str, str]:
    """Return (ISBAR text, who_drafted). Tries the local model first, then falls back to rules."""
    identify = f"{person['name']}, Room {100 + person['resident_id']}. {shift['label']}. Handover from {carer_name}."
    conditions = ", ".join(c["name"] for c in person.get("conditions", []))
    lines = [f"Resident: {person['name']}", f"Recorded conditions: {conditions or 'none recorded'}"]
    lines += [f"- {e['at'][11:16]} {e['kind']}: {e['text']} (by {e['by']})" for e in src["entries"]]
    if src["not_done"]:
        lines.append("- Care plan not done yet: " + ", ".join(src["not_done"]))
    if src["entries"] or src["not_done"]:
        source = "\n".join(lines)
        try:
            parts = ask_model(HANDOVER_SYSTEM, source, ISBAR_FIELDS)
            if all(len(parts[f]) > 3 for f in ISBAR_FIELDS) and not new_unsafe_words(" ".join(parts.values()), source):
                return isbar_text(identify, parts), "AI"
        except Exception:
            pass  # Ollama off, slow or bad JSON: the carer still gets a draft
    return isbar_text(identify, rules_isbar(person, src)), "Rules"


def draft_family_from_handover(person: dict, handover_text: str) -> tuple[str, str]:
    first = person["name"].split(" ")[0]
    try:
        text = ask_model(FAMILY_FROM_HANDOVER_SYSTEM, f"Resident: {person['name']}\nHandover:\n{handover_text}")["text"]
        if len(text) > 20 and not guidance.contains_blocked(text) and not CLINICAL_FOR_FAMILY.search(text):
            return text, "AI"
    except Exception:
        pass
    return (
        f"Kia ora. Here is today's update for {first}. The care team looked after {first} today, "
        "and the nurse has read the shift handover.\nPlease message us anytime if you have questions.",
        "Rules",
    )


def handover_out(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["sources"] = json.loads(out["sources"])
    person = guidance.load_resident(out["resident_id"])
    out["resident"] = person["name"] if person else f"Resident {out['resident_id']}"
    return out


def get_handover(con: sqlite3.Connection, handover_id: int) -> sqlite3.Row:
    row = con.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Handover not found.")
    return row


def message_out(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["urgent"] = out.get("sender_role") == "family" and bool(URGENT_FAMILY.search(out["text"]))
    return out


def out_of_hours(moment: datetime | None = None) -> bool:
    hour = (moment or datetime.now()).hour
    return not REPLY_HOURS[0] <= hour < REPLY_HOURS[1]


# ---------- pages ----------
@router.get("/handover", include_in_schema=False)
def carer_handover_page():
    return FileResponse(STATIC_DIR / "handover.html")


@router.get("/nurse/handover", include_in_schema=False)
def nurse_handover_page():
    return FileResponse(STATIC_DIR / "nurse-handover.html")


@router.get("/nurse/schedule", include_in_schema=False)
def schedule_page():
    return FileResponse(STATIC_DIR / "schedule.html")


@router.get("/api/shifts")
def shifts(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    signed_in(("carer", "nurse"), authorization, x_session_token)
    return shifts_now()


@router.get("/api/workflow/counts")
def workflow_counts(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Small numbers for the navigation bar badges."""
    sess = signed_in(("carer", "nurse", "manager", "family"), authorization, x_session_token)
    con = get_db()
    try:
        if sess["role"] == "nurse":
            waiting = con.execute("SELECT COUNT(*) FROM handovers WHERE status = 'waiting'").fetchone()[0]
            unread = [message_out(r) for r in con.execute(
                "SELECT * FROM family_messages WHERE sender_role = 'family' AND read_by IS NULL"
            )]
            return {"waiting_handovers": waiting, "unread_messages": len(unread),
                    "urgent_messages": sum(1 for m in unread if m["urgent"])}
        if sess["role"] == "carer":
            back = con.execute(
                "SELECT COUNT(*) FROM handovers WHERE status = 'returned' AND carer_user = ?", (sess["username"],)
            ).fetchone()[0]
            return {"returned_handovers": back}
        return {}
    finally:
        con.close()


# ---------- quick notes ----------
class NoteIn(BaseModel):
    resident_id: int
    text: str = Field(min_length=2, max_length=600)


@router.post("/api/carer/notes", status_code=201)
def add_note(body: NoteIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    portal.resident_or_404(body.resident_id)
    con = get_db()
    with con:
        cur = con.execute(
            "INSERT INTO carer_notes (resident_id, text, carer, carer_user, created_at) VALUES (?, ?, ?, ?, ?)",
            (body.resident_id, body.text.strip(), sess["full_name"], sess["username"], now()),
        )
        row = con.execute("SELECT * FROM carer_notes WHERE id = ?", (cur.lastrowid,)).fetchone()
    con.close()
    return dict(row)


@router.get("/api/carer/notes")
def list_notes(
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Today's quick notes, newest first, for one resident or everyone."""
    signed_in(("carer", "nurse"), authorization, x_session_token)
    sql, args = "SELECT * FROM carer_notes WHERE created_at >= ?", [today()]
    if resident_id is not None:
        sql += " AND resident_id = ?"
        args.append(resident_id)
    con = get_db()
    rows = con.execute(sql + " ORDER BY created_at DESC, id DESC", args).fetchall()
    con.close()
    return [dict(r) for r in rows]


@router.delete("/api/carer/notes/{note_id}")
def delete_note(note_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """A carer can remove their own note from today, for example a typo."""
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    row = con.execute("SELECT * FROM carer_notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Note not found.")
    if row["carer_user"] != sess["username"] or not row["created_at"].startswith(today()):
        con.close()
        raise HTTPException(403, "You can only remove your own notes from today.")
    with con:
        con.execute("DELETE FROM carer_notes WHERE id = ?", (note_id,))
    con.close()
    return {"ok": True}


# ---------- care plan (daily or chosen days) ----------
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ScheduleEdit(BaseModel):
    task: str = Field(min_length=2, max_length=60)
    time: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    note: str = Field(default="", max_length=200)
    days: list[Day] = []           # empty, or all seven, means every day
    medicine: bool | None = None   # None: decide from the task name


class ScheduleIn(ScheduleEdit):
    resident_id: int


class DoneIn(BaseModel):
    done: bool


def days_value(days: list[str]) -> str:
    chosen = [d for d in DAYS if d in set(days)]
    return "" if len(chosen) in (0, 7) else ",".join(chosen)


def is_medicine(body: ScheduleEdit) -> bool:
    return body.medicine if body.medicine is not None else bool(MEDICINE_WORDS.search(body.task))


@router.get("/api/schedule")
def get_schedule(
    resident_id: int,
    scope: Literal["today", "all"] = "today",
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Today's care plan with who ticked each item off. scope=all also lists items for other days."""
    signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    rows = schedule_rows(con, resident_id, every=scope == "all")
    con.close()
    return rows


@router.post("/api/schedule", status_code=201)
def add_schedule(body: ScheduleIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    sess = signed_in(("nurse",), authorization, x_session_token)
    portal.resident_or_404(body.resident_id)
    con = get_db()
    with con:
        cur = con.execute(
            "INSERT INTO care_schedule (resident_id, task, time, note, days, medicine, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body.resident_id, body.task.strip(), body.time, body.note.strip(), days_value(body.days),
             int(is_medicine(body)), sess["full_name"], now()),
        )
    item = next(i for i in schedule_rows(con, body.resident_id, every=True) if i["id"] == cur.lastrowid)
    con.close()
    portal.audit(sess["full_name"], "nurse", "schedule_task_added", body.resident_id, f"{body.time} {body.task}".strip())
    return item


@router.put("/api/schedule/{item_id}")
def edit_schedule(
    item_id: int,
    body: ScheduleEdit,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = signed_in(("nurse",), authorization, x_session_token)
    con = get_db()
    row = con.execute("SELECT * FROM care_schedule WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Task not found.")
    with con:
        con.execute(
            "UPDATE care_schedule SET task = ?, time = ?, note = ?, days = ?, medicine = ?, updated_at = ? WHERE id = ?",
            (body.task.strip(), body.time, body.note.strip(), days_value(body.days), int(is_medicine(body)), now(), item_id),
        )
    item = next(i for i in schedule_rows(con, row["resident_id"], every=True) if i["id"] == item_id)
    con.close()
    portal.audit(sess["full_name"], "nurse", "schedule_task_changed", row["resident_id"], f"{body.time} {body.task}".strip())
    return item


@router.delete("/api/schedule/{item_id}")
def remove_schedule(item_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Stops the task from tomorrow's list. Past ticks stay for the record."""
    sess = signed_in(("nurse",), authorization, x_session_token)
    con = get_db()
    row = con.execute("SELECT * FROM care_schedule WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Task not found.")
    with con:
        con.execute("UPDATE care_schedule SET active = 0, updated_at = ? WHERE id = ?", (now(), item_id))
    con.close()
    portal.audit(sess["full_name"], "nurse", "schedule_task_removed", row["resident_id"], row["task"])
    return {"ok": True}


@router.post("/api/schedule/{item_id}/done")
def tick_schedule(
    item_id: int,
    body: DoneIn,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    row = con.execute("SELECT * FROM care_schedule WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Task not found.")
    if row["medicine"] and not auth.can_give_medicines(sess["username"], sess["role"]):
        con.close()
        raise HTTPException(
            403, "Only a nurse, or a carer signed off as medication competent, can tick a medicine round. Tell the nurse."
        )
    with con:
        if body.done:
            con.execute(
                "INSERT OR IGNORE INTO schedule_done (schedule_id, day, done_by, done_at) VALUES (?, ?, ?, ?)",
                (item_id, today(), sess["full_name"], now()),
            )
        else:
            con.execute("DELETE FROM schedule_done WHERE schedule_id = ? AND day = ?", (item_id, today()))
    item = next((s for s in schedule_rows(con, row["resident_id"], every=True) if s["id"] == item_id), None)
    con.close()
    if row["medicine"]:
        portal.audit(sess["full_name"], sess["role"], "medicine_round_ticked" if body.done else "medicine_round_unticked",
                     row["resident_id"], row["task"])
    return item


# ---------- handover ----------
class HandoverDraftIn(BaseModel):
    resident_id: int
    shift: Literal["current", "previous"] = "current"


class HandoverTextIn(BaseModel):
    text: str = Field(min_length=10, max_length=3000)


class HandoverReviewIn(BaseModel):
    decision: Literal["approve", "return"]
    text: str = Field(min_length=10, max_length=3000)
    note: str = Field(default="", max_length=500)


@router.post("/api/handovers/draft")
def draft_handover(body: HandoverDraftIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """The AI drafts an ISBAR handover from one shift's records. Only the carer sees it until they send it."""
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    person = portal.resident_or_404(body.resident_id)
    shift = shifts_now()[body.shift]
    con = get_db()
    since = handover_window(con, body.resident_id, shift)
    con.close()
    src = shift_sources(body.resident_id, since, shift)
    text, by = draft_handover_text(person, src, shift, sess["full_name"])
    con = get_db()
    with con:
        # one open draft per carer, resident and shift: replace the old one
        con.execute(
            "DELETE FROM handovers WHERE resident_id = ? AND carer_user = ? AND shift_key = ? AND status = 'draft'",
            (body.resident_id, sess["username"], shift["key"]),
        )
        cur = con.execute(
            "INSERT INTO handovers (resident_id, carer, carer_user, status, ai_text, text, drafted_by, sources, since, "
            "created_at, shift_key, shift_label) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)",
            (body.resident_id, sess["full_name"], sess["username"], text, text, by, json.dumps(src), since, now(),
             shift["key"], shift["label"]),
        )
        row = get_handover(con, cur.lastrowid)
    con.close()
    portal.audit(by, "system", "handover_drafted", body.resident_id, f"{shift['label']}, for {sess['full_name']}")
    return handover_out(row)


@router.post("/api/handovers/{handover_id}/send")
def send_handover(
    handover_id: int,
    body: HandoverTextIn,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    row = get_handover(con, handover_id)
    if row["carer_user"] != sess["username"]:
        con.close()
        raise HTTPException(403, "Only the carer who drafted this handover can send it.")
    if row["status"] not in ("draft", "returned"):
        con.close()
        raise HTTPException(409, "This handover has already been sent.")
    with con:
        con.execute(
            "UPDATE handovers SET text = ?, status = 'waiting', sent_at = ?, review_note = '' WHERE id = ?",
            (body.text.strip(), now(), handover_id),
        )
        row = get_handover(con, handover_id)
    con.close()
    edited = body.text.strip() != row["ai_text"].strip()
    portal.audit(sess["full_name"], sess["role"], "handover_sent", row["resident_id"], "edited by carer" if edited else "")
    return handover_out(row)


@router.get("/api/handovers")
def list_handovers(
    status: Literal["draft", "waiting", "approved", "returned"] | None = None,
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """With a status: every handover in that status. Without one: handovers from the last 24 hours."""
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    sql, args = "SELECT * FROM handovers WHERE 1 = 1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    else:
        sql += " AND created_at >= ?"
        args.append((datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds"))
    if resident_id is not None:
        sql += " AND resident_id = ?"
        args.append(resident_id)
    con = get_db()
    rows = con.execute(sql + " ORDER BY id DESC", args).fetchall()
    con.close()
    out = [handover_out(r) for r in rows]
    # drafts are private to the carer who made them
    return [h for h in out if h["status"] != "draft" or h["carer_user"] == sess["username"]]


@router.get("/api/handovers/{handover_id}")
def one_handover(handover_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    row = get_handover(con, handover_id)
    con.close()
    return handover_out(row)


@router.post("/api/handovers/{handover_id}/review")
def review_handover(
    handover_id: int,
    body: HandoverReviewIn,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """The nurse approves the handover (with any edits) or sends it back to the carer with a reason."""
    sess = signed_in(("nurse",), authorization, x_session_token)
    if body.decision == "return" and not body.note.strip():
        raise HTTPException(422, "Write a short note telling the carer what to change.")
    con = get_db()
    row = get_handover(con, handover_id)
    if row["status"] != "waiting":
        con.close()
        raise HTTPException(409, "Only a handover waiting for a nurse can be reviewed.")
    status = "approved" if body.decision == "approve" else "returned"
    with con:
        con.execute(
            "UPDATE handovers SET status = ?, text = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (status, body.text.strip(), sess["full_name"], now(), body.note.strip(), handover_id),
        )
        new_row = get_handover(con, handover_id)
    con.close()
    if status == "approved":
        detail = "edited by nurse" if body.text.strip() != row["text"].strip() else ""
        portal.audit(sess["full_name"], "nurse", "handover_approved", row["resident_id"], detail)
    else:
        portal.audit(sess["full_name"], "nurse", "handover_returned", row["resident_id"], body.note.strip())
    return handover_out(new_row)


@router.post("/api/handovers/{handover_id}/family-draft")
def family_draft_from_handover(
    handover_id: int,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Draft a family update from an approved handover. The nurse sends it with /api/family-updates/{id}/send."""
    sess = signed_in(("nurse",), authorization, x_session_token)
    con = get_db()
    row = get_handover(con, handover_id)
    if row["status"] != "approved":
        con.close()
        raise HTTPException(409, "Approve the handover before drafting a family update.")
    con.close()
    person = portal.resident_or_404(row["resident_id"])
    text, by = draft_family_from_handover(person, row["text"])
    con = get_db()
    with con:
        con.execute("DELETE FROM family_updates WHERE resident_id = ? AND status = 'draft'", (row["resident_id"],))
        cur = con.execute(
            "INSERT INTO family_updates (resident_id, text, status, drafted_by, created_at) VALUES (?, ?, 'draft', ?, ?)",
            (row["resident_id"], text, by, now()),
        )
        update_id = cur.lastrowid
        con.execute("UPDATE handovers SET family_update_id = ? WHERE id = ?", (update_id, handover_id))
    con.close()
    portal.audit(by, "system", "family_update_drafted", row["resident_id"], f"from handover, requested by {sess['full_name']}")
    return {"id": update_id, "resident_id": row["resident_id"], "text": text, "status": "draft", "drafted_by": by}


# ---------- nurse and family messages ----------
class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


CHAT_COLUMNS = "id, resident_id, from_name, sender_role, text, created_at, read_by"


@router.get("/api/chat/urgent")
def urgent_messages(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Unread family messages that mention a fall, pain, breathing, hospital and similar."""
    signed_in(("nurse",), authorization, x_session_token)
    con = get_db()
    rows = con.execute(
        f"SELECT {CHAT_COLUMNS} FROM family_messages WHERE sender_role = 'family' AND read_by IS NULL ORDER BY id DESC"
    ).fetchall()
    con.close()
    return [m for m in (message_out(r) for r in rows) if m["urgent"]]


@router.get("/api/chat/{resident_id}")
def chat_thread(resident_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """All messages between the family and the nurses about one resident, oldest first."""
    sess = signed_in(("nurse", "family"), authorization, x_session_token)
    own_resident_only(sess, resident_id)
    con = get_db()
    rows = con.execute(
        f"SELECT {CHAT_COLUMNS} FROM family_messages WHERE resident_id = ? ORDER BY id DESC LIMIT 200",
        (resident_id,),
    ).fetchall()
    con.close()
    return [message_out(r) for r in reversed(rows)]


@router.post("/api/chat/{resident_id}", status_code=201)
def chat_send(
    resident_id: int,
    body: ChatIn,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = signed_in(("nurse", "family"), authorization, x_session_token)
    own_resident_only(sess, resident_id)
    portal.resident_or_404(resident_id)
    is_nurse = sess["role"] == "nurse"
    con = get_db()
    with con:
        cur = con.execute(
            "INSERT INTO family_messages (resident_id, from_name, from_user, text, created_at, sender_role, read_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (resident_id, sess["full_name"], sess["username"], body.text.strip(), now(), sess["role"],
             sess["full_name"] if is_nurse else None),
        )
        row = con.execute(f"SELECT {CHAT_COLUMNS} FROM family_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    con.close()
    out = message_out(row)
    portal.audit(sess["full_name"], sess["role"], "nurse_message_sent" if is_nurse else "family_message_sent", resident_id,
                 "flagged urgent" if out["urgent"] else "")
    out["out_of_hours"] = out_of_hours()
    return out


@router.post("/api/chat/{resident_id}/read")
def chat_read(resident_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """The nurse marks the family's messages about this resident as read."""
    sess = signed_in(("nurse",), authorization, x_session_token)
    con = get_db()
    with con:
        cur = con.execute(
            "UPDATE family_messages SET read_by = ? WHERE resident_id = ? AND sender_role = 'family' AND read_by IS NULL",
            (sess["full_name"], resident_id),
        )
    con.close()
    return {"ok": True, "marked": cur.rowcount}
