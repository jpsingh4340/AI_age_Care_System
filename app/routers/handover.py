# Carer to nurse handover workflow.
#
#   carer   writes quick notes during the shift and ticks off the nurse's daily schedule
#   carer   asks the AI to draft a handover from what was recorded, edits it, and sends it to the nurse
#   nurse   reads the draft next to the carer's source notes, edits it, then approves it or sends it back
#   nurse   keeps a daily care schedule (shower, meals, exercise...) for each resident
#   nurse   drafts a family update from an approved handover, then sends it with the family update API
#   nurse and family   message each other about one resident
#
# Every endpoint checks the signed-in user's session and role on the server.
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import guidance, ollama_client
from app.config import CHAT_MODEL
from app.prompts import FAMILY_FROM_HANDOVER_SYSTEM, HANDOVER_SYSTEM
from app.routers import carer, portal

router = APIRouter(tags=["Handover"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
STATUS_TEXT = {"given": "done", "refused": "refused", "not_done": "not done"}

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


# ---------- helpers ----------
def get_db() -> sqlite3.Connection:
    con = portal.get_db()  # also creates the family tables
    con.executescript(SCHEMA)
    columns = [r["name"] for r in con.execute("PRAGMA table_info(family_messages)")]
    if "sender_role" not in columns:
        con.execute("ALTER TABLE family_messages ADD COLUMN sender_role TEXT NOT NULL DEFAULT 'family'")
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


def schedule_rows(con: sqlite3.Connection, resident_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT s.*, d.done_by, d.done_at FROM care_schedule s "
        "LEFT JOIN schedule_done d ON d.schedule_id = s.id AND d.day = ? "
        "WHERE s.resident_id = ? AND s.active = 1 "
        "ORDER BY CASE WHEN s.time = '' THEN 1 ELSE 0 END, s.time, s.id",
        (today(), resident_id),
    ).fetchall()
    return [dict(r) for r in rows]


def shift_start(con: sqlite3.Connection, resident_id: int) -> str:
    """The shift starts after the last handover sent today, or at midnight."""
    start = today() + "T00:00:00"
    row = con.execute(
        "SELECT MAX(sent_at) FROM handovers WHERE resident_id = ? AND status IN ('waiting', 'approved') AND sent_at >= ?",
        (resident_id, start),
    ).fetchone()
    return row[0] or start


def shift_sources(resident_id: int, since: str) -> dict:
    """Everything carers recorded for one resident since `since`, oldest first, plus scheduled tasks still to do."""
    entries = []
    rid = str(resident_id)
    con = carer.get_db()
    try:
        for r in con.execute("SELECT * FROM carer_tasks WHERE resident_id = ? AND created_at > ?", (rid, since)):
            entries.append({"at": r["created_at"], "kind": "Task", "text": f"{r['task']}: {STATUS_TEXT.get(r['status'], r['status'])}", "by": r["carer"]})
        for r in con.execute("SELECT * FROM carer_vitals WHERE resident_id = ? AND created_at > ?", (rid, since)):
            entries.append({"at": r["created_at"], "kind": "Vital signs", "text": vitals_text(r), "by": r["carer"]})
        for r in con.execute("SELECT * FROM carer_concerns WHERE resident_id = ? AND created_at > ?", (rid, since)):
            entries.append({"at": r["created_at"], "kind": "Concern", "text": f"{r['type']}: {r['note']}", "by": r["carer"]})
    finally:
        con.close()

    con = get_db()
    try:
        for r in con.execute("SELECT * FROM carer_notes WHERE resident_id = ? AND created_at > ?", (resident_id, since)):
            entries.append({"at": r["created_at"], "kind": "Note", "text": r["text"], "by": r["carer"]})
        not_done = []
        for s in schedule_rows(con, resident_id):
            label = (s["time"] + " " if s["time"] else "") + s["task"]
            if s["done_at"] and s["done_at"] > since:
                entries.append({"at": s["done_at"], "kind": "Schedule", "text": f"{s['task']}: done", "by": s["done_by"]})
            elif not s["done_at"]:
                not_done.append(label)
    finally:
        con.close()

    entries.sort(key=lambda e: e["at"])
    return {"entries": entries, "not_done": not_done}


def new_unsafe_words(text: str, source: str) -> bool:
    """True if the AI added a medicine, dose or diagnosis word that the carer never wrote."""
    lower = source.lower()
    words = {w.lower() for w in guidance.BLOCKED_WORDS.findall(text)}
    if any(w not in lower for w in words):
        return True
    return any(m.group(0).lower() not in lower for m in guidance.DOSE_PATTERN.finditer(text))


def ask_model(system: str, user: str) -> str:
    data = ollama_client._post(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "stream": False,
            "format": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            "options": {"temperature": 0.2, "num_predict": 320, "num_gpu": ollama_client.NUM_GPU},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=90,
    )
    return json.loads(data["message"]["content"]).get("text", "").strip()


def rules_handover(name: str, src: dict) -> str:
    """Used when the AI is not available, or wrote something unsafe."""
    first = name.split(" ")[0]
    entries = src["entries"]
    if not entries and not src["not_done"]:
        return f"Nothing was recorded for {first} this shift."
    lines = []
    concerns = [e["text"] for e in entries if e["kind"] == "Concern"]
    flagged = [e["text"] for e in entries if e["kind"] == "Vital signs" and "outside usual range" in e["text"]]
    if concerns:
        lines.append("Concerns: " + "; ".join(concerns) + ".")
    if flagged:
        lines.append("Readings outside the usual range: " + "; ".join(flagged) + ".")
    done = [e["text"] for e in entries if e["kind"] in ("Task", "Schedule")]
    if done:
        lines.append("Care this shift: " + "; ".join(done) + ".")
    notes = [e["text"] for e in entries if e["kind"] == "Note"]
    if notes:
        lines.append("Carer notes: " + " ".join(n.rstrip(".") + "." for n in notes))
    if src["not_done"]:
        lines.append("Scheduled but not done yet: " + ", ".join(src["not_done"]) + ".")
    return f"Handover for {first}. " + " ".join(lines)


def draft_handover_text(person: dict, src: dict) -> tuple[str, str]:
    """Return (text, who_drafted). Tries the local model first, then falls back to rules."""
    lines = [f"Resident: {person['name']}"]
    lines += [f"- {e['at'][11:16]} {e['kind']}: {e['text']} (by {e['by']})" for e in src["entries"]]
    if src["not_done"]:
        lines.append("- Scheduled tasks not done yet: " + ", ".join(src["not_done"]))
    if len(lines) == 1:
        return rules_handover(person["name"], src), "Rules"
    source = "\n".join(lines)
    try:
        text = ask_model(HANDOVER_SYSTEM, source)
        if len(text) > 20 and not new_unsafe_words(text, source):
            return text, "AI"
    except Exception:
        pass  # Ollama off, slow or bad JSON: the carer still gets a draft
    return rules_handover(person["name"], src), "Rules"


def draft_family_from_handover(person: dict, handover_text: str) -> tuple[str, str]:
    first = person["name"].split(" ")[0]
    try:
        text = ask_model(FAMILY_FROM_HANDOVER_SYSTEM, f"Resident: {person['name']}\nHandover:\n{handover_text}")
        if len(text) > 20 and not guidance.contains_blocked(text):
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


# ---------- daily care schedule ----------
class ScheduleIn(BaseModel):
    resident_id: int
    task: str = Field(min_length=2, max_length=60)
    time: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    note: str = Field(default="", max_length=200)


class ScheduleEdit(BaseModel):
    task: str = Field(min_length=2, max_length=60)
    time: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    note: str = Field(default="", max_length=200)


class DoneIn(BaseModel):
    done: bool


@router.get("/api/schedule")
def get_schedule(resident_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """The resident's daily tasks, with who ticked each one off today."""
    signed_in(("carer", "nurse"), authorization, x_session_token)
    con = get_db()
    rows = schedule_rows(con, resident_id)
    con.close()
    return rows


@router.post("/api/schedule", status_code=201)
def add_schedule(body: ScheduleIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    sess = signed_in(("nurse",), authorization, x_session_token)
    portal.resident_or_404(body.resident_id)
    con = get_db()
    with con:
        cur = con.execute(
            "INSERT INTO care_schedule (resident_id, task, time, note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (body.resident_id, body.task.strip(), body.time, body.note.strip(), sess["full_name"], now()),
        )
        row = con.execute("SELECT * FROM care_schedule WHERE id = ?", (cur.lastrowid,)).fetchone()
    con.close()
    portal.audit(sess["full_name"], "nurse", "schedule_task_added", body.resident_id, f"{body.time} {body.task}".strip())
    return dict(row)


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
            "UPDATE care_schedule SET task = ?, time = ?, note = ?, updated_at = ? WHERE id = ?",
            (body.task.strip(), body.time, body.note.strip(), now(), item_id),
        )
        row = con.execute("SELECT * FROM care_schedule WHERE id = ?", (item_id,)).fetchone()
    con.close()
    portal.audit(sess["full_name"], "nurse", "schedule_task_changed", row["resident_id"], f"{body.time} {body.task}".strip())
    return dict(row)


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
    with con:
        if body.done:
            con.execute(
                "INSERT OR IGNORE INTO schedule_done (schedule_id, day, done_by, done_at) VALUES (?, ?, ?, ?)",
                (item_id, today(), sess["full_name"], now()),
            )
        else:
            con.execute("DELETE FROM schedule_done WHERE schedule_id = ? AND day = ?", (item_id, today()))
    item = next((s for s in schedule_rows(con, row["resident_id"]) if s["id"] == item_id), None)
    con.close()
    return item


# ---------- handover ----------
class HandoverDraftIn(BaseModel):
    resident_id: int


class HandoverTextIn(BaseModel):
    text: str = Field(min_length=10, max_length=3000)


class HandoverReviewIn(BaseModel):
    decision: Literal["approve", "return"]
    text: str = Field(min_length=10, max_length=3000)
    note: str = Field(default="", max_length=500)


@router.post("/api/handovers/draft")
def draft_handover(body: HandoverDraftIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """The AI drafts a handover from this shift's records. Only the carer sees it until they send it."""
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    person = portal.resident_or_404(body.resident_id)
    con = get_db()
    since = shift_start(con, body.resident_id)
    con.close()
    src = shift_sources(body.resident_id, since)
    text, by = draft_handover_text(person, src)
    con = get_db()
    with con:
        # one open draft per carer and resident: replace the old one
        con.execute(
            "DELETE FROM handovers WHERE resident_id = ? AND carer_user = ? AND status = 'draft'",
            (body.resident_id, sess["username"]),
        )
        cur = con.execute(
            "INSERT INTO handovers (resident_id, carer, carer_user, status, ai_text, text, drafted_by, sources, since, created_at) "
            "VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
            (body.resident_id, sess["full_name"], sess["username"], text, text, by, json.dumps(src), since, now()),
        )
        row = get_handover(con, cur.lastrowid)
    con.close()
    portal.audit(by, "system", "handover_drafted", body.resident_id, f"for {sess['full_name']}")
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
    """With a status: every handover in that status. Without one: today's handovers."""
    sess = signed_in(("carer", "nurse"), authorization, x_session_token)
    sql, args = "SELECT * FROM handovers WHERE 1 = 1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    else:
        sql += " AND created_at >= ?"
        args.append(today())
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


@router.get("/api/chat/{resident_id}")
def chat_thread(resident_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """All messages between the family and the nurses about one resident, oldest first."""
    sess = signed_in(("nurse", "family"), authorization, x_session_token)
    own_resident_only(sess, resident_id)
    con = get_db()
    rows = con.execute(
        "SELECT id, from_name, sender_role, text, created_at, read_by FROM family_messages "
        "WHERE resident_id = ? ORDER BY id DESC LIMIT 200",
        (resident_id,),
    ).fetchall()
    con.close()
    return [dict(r) for r in reversed(rows)]


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
        row = con.execute(
            "SELECT id, from_name, sender_role, text, created_at, read_by FROM family_messages WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    con.close()
    portal.audit(sess["full_name"], sess["role"], "nurse_message_sent" if is_nurse else "family_message_sent", resident_id)
    return dict(row)


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
