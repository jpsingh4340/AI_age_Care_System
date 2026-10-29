# Role pages added for the four-role app (carer, nurse, manager, family).
#
#   nurse   drafts a family update (AI writes it from today's carer records), edits, approves and sends it
#   family  sees only nurse-approved updates for their own resident, and can message the care team
#   nurse   reads family messages
#   manager sees an overview, the audit log, and creates logins for staff and families
#
# Every endpoint checks the signed-in user's session token and role on the server.
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app import auth, db, guidance, ollama_client
from app.config import CHAT_MODEL
from app.schemas import (
    CreateUserRequest,
    FamilyMessageRequest,
    FamilyUpdateDraftRequest,
    FamilyUpdateSendRequest,
)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "static"

SCHEMA = """
CREATE TABLE IF NOT EXISTS family_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | sent
    drafted_by TEXT NOT NULL,               -- 'AI' or 'Rules' (when the AI is not available)
    approved_by TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS family_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    from_name TEXT NOT NULL,
    from_user TEXT NOT NULL,
    text TEXT NOT NULL,
    read_by TEXT,
    created_at TEXT NOT NULL
);
"""


# ---------- helpers ----------
def get_db() -> sqlite3.Connection:
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require(roles: tuple[str, ...], authorization: str, x_session_token: str) -> dict:
    """Return the signed-in user, or stop with 401 (not signed in) / 403 (wrong role)."""
    sess = auth.session_from_headers(authorization, x_session_token)
    if not sess:
        raise HTTPException(401, "Please sign in.")
    if sess["role"] not in roles:
        raise HTTPException(403, "Your account does not have access to this.")
    return sess


def audit(actor: str, role: str, action: str, resident_id: int | None = None, detail: str = "") -> None:
    with db.session() as conn:
        db._audit(conn, actor, role, action, resident_id, None, detail)


def resident_or_404(resident_id: int) -> dict:
    person = guidance.load_resident(resident_id)
    if not person:
        raise HTTPException(404, "Resident not found.")
    return person


def today_records(resident_id: int) -> dict:
    """What carers recorded today for one resident (tables belong to the carer page)."""
    day = datetime.now().date().isoformat() + "%"
    out = {"tasks": [], "concerns": [], "vitals": []}
    con = get_db()
    try:
        for name in out:
            try:
                rows = con.execute(
                    f"SELECT * FROM carer_{name} WHERE resident_id = ? AND created_at LIKE ? ORDER BY created_at",
                    (str(resident_id), day),
                ).fetchall()
                out[name] = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass  # carer tables not created yet
    finally:
        con.close()
    return out


# ---------- pages ----------
@router.get("/", include_in_schema=False)
def root():
    """Everyone starts at the sign-in page, which sends them to their own role page."""
    return RedirectResponse("/login")


@router.get("/manager", include_in_schema=False)
def manager_page():
    return FileResponse(STATIC_DIR / "manager.html")


@router.get("/family", include_in_schema=False)
def family_page():
    return FileResponse(STATIC_DIR / "family.html")


# ---------- family updates: AI drafts, nurse approves, family reads ----------
FAMILY_SYSTEM = (
    "You write a short, warm daily update for the family of an aged-care resident. "
    "Use plain, kind language, 3 to 5 sentences. Start with 'Kia ora'. "
    "Do NOT include diagnoses, medicines, vital sign numbers or anything frightening. "
    "If there was a concern, say gently that the nurse has checked and the team is keeping an eye on it. "
    "Only use facts from the notes. Return JSON with one field: text."
)


def rule_based_update(name: str, rec: dict) -> str:
    """Used when the AI is not available. Same idea as the prototype's familyDraft()."""
    first = name.split(" ")[0]
    done = [t["task"].lower() for t in rec["tasks"] if t["status"] == "given"]
    text = f"Kia ora, here is today's update for {first}. {first} was well looked after by the team today."
    if done:
        text += " The team helped with: " + ", ".join(dict.fromkeys(done)) + "."
    if rec["concerns"]:
        kinds = ", ".join(dict.fromkeys(c["type"].lower() for c in rec["concerns"]))
        text += f" Our nurse has checked on {first} about {kinds}, and the team is keeping a close eye on it."
    else:
        text += " There were no concerns today."
    return text + "\nPlease message us anytime if you have questions."


def draft_family_text(person: dict, rec: dict) -> tuple[str, str]:
    """Return (text, who_drafted). Tries the local SLM first, then falls back to rules."""
    lines = [f"Resident: {person['name']}"]
    lines += [f"- {t['created_at'][11:16]} {t['task']}: {t['status']}" for t in rec["tasks"]]
    lines += [f"- Concern ({c['type']}): {c['note']}" for c in rec["concerns"]]
    if len(lines) == 1:
        lines.append("- No care tasks or concerns recorded yet today.")
    try:
        data = ollama_client._post(
            "/api/chat",
            {
                "model": CHAT_MODEL,
                "stream": False,
                "format": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                "options": {"temperature": 0.2, "num_predict": 220, "num_gpu": ollama_client.NUM_GPU},
                "messages": [
                    {"role": "system", "content": FAMILY_SYSTEM},
                    {"role": "user", "content": "\n".join(lines)},
                ],
            },
            timeout=30,
        )
        text = json.loads(data["message"]["content"]).get("text", "").strip()
        if len(text) > 20:
            return text, "AI"
    except Exception:
        pass  # Ollama off, slow or bad JSON - the nurse still gets a draft
    return rule_based_update(person["name"], rec), "Rules"


@router.post("/api/family-updates/draft")
def draft_family_update(
    body: FamilyUpdateDraftRequest,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("nurse",), authorization, x_session_token)
    person = resident_or_404(body.resident_id)
    text, by = draft_family_text(person, today_records(body.resident_id))
    con = get_db()
    with con:
        # one open draft per resident: replace the old one
        con.execute("DELETE FROM family_updates WHERE resident_id = ? AND status = 'draft'", (body.resident_id,))
        cur = con.execute(
            "INSERT INTO family_updates (resident_id, text, status, drafted_by, created_at) VALUES (?, ?, 'draft', ?, ?)",
            (body.resident_id, text, by, now()),
        )
        update_id = cur.lastrowid
    con.close()
    audit(by, "system", "family_update_drafted", body.resident_id, f"requested by {sess['full_name']}")
    return {"id": update_id, "resident_id": body.resident_id, "text": text, "status": "draft", "drafted_by": by}


@router.get("/api/family-updates")
def list_family_updates(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    require(("nurse", "manager"), authorization, x_session_token)
    con = get_db()
    rows = con.execute("SELECT * FROM family_updates ORDER BY id DESC LIMIT 50").fetchall()
    con.close()
    return [dict(r) for r in rows]


@router.post("/api/family-updates/{update_id}/send")
def send_family_update(
    update_id: int,
    body: FamilyUpdateSendRequest,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("nurse",), authorization, x_session_token)
    con = get_db()
    row = con.execute("SELECT * FROM family_updates WHERE id = ?", (update_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Update not found.")
    if row["status"] == "sent":
        con.close()
        raise HTTPException(400, "This update was already sent.")
    edited = body.text.strip() != row["text"].strip()
    with con:
        con.execute(
            "UPDATE family_updates SET text = ?, status = 'sent', approved_by = ?, sent_at = ? WHERE id = ?",
            (body.text.strip(), sess["full_name"], now(), update_id),
        )
    con.close()
    audit(sess["full_name"], "nurse", "family_update_approved", row["resident_id"], "edited by nurse" if edited else "")
    return {"ok": True}


# ---------- family portal ----------
@router.get("/api/family/me")
def family_me(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Everything a family member may see: their resident's name and nurse-approved updates only."""
    sess = require(("family",), authorization, x_session_token)
    rid = sess["resident_id"]
    person = resident_or_404(rid)
    con = get_db()
    updates = con.execute(
        "SELECT text, approved_by, sent_at FROM family_updates WHERE resident_id = ? AND status = 'sent' "
        "ORDER BY sent_at DESC LIMIT 10",
        (rid,),
    ).fetchall()
    msgs = con.execute(
        "SELECT text, created_at, read_by FROM family_messages WHERE from_user = ? ORDER BY id DESC LIMIT 20",
        (sess["username"],),
    ).fetchall()
    con.close()
    return {
        "resident": {"resident_id": rid, "name": person["name"], "room": f"Room {100 + rid}"},
        "updates": [dict(u) for u in updates],
        "messages": [dict(m) for m in msgs],
    }


@router.post("/api/family/messages", status_code=201)
def family_send_message(
    body: FamilyMessageRequest,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("family",), authorization, x_session_token)
    con = get_db()
    with con:
        con.execute(
            "INSERT INTO family_messages (resident_id, from_name, from_user, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (sess["resident_id"], sess["full_name"], sess["username"], body.text.strip(), now()),
        )
    con.close()
    audit(sess["full_name"], "family", "family_message_sent", sess["resident_id"])
    return {"ok": True}


@router.get("/api/messages")
def staff_messages(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    require(("nurse", "manager"), authorization, x_session_token)
    con = get_db()
    rows = con.execute("SELECT * FROM family_messages ORDER BY id DESC LIMIT 50").fetchall()
    con.close()
    return [dict(r) for r in rows]


@router.post("/api/messages/{message_id}/read")
def mark_message_read(
    message_id: int,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("nurse",), authorization, x_session_token)
    con = get_db()
    with con:
        cur = con.execute("UPDATE family_messages SET read_by = ? WHERE id = ?", (sess["full_name"], message_id))
    con.close()
    if not cur.rowcount:
        raise HTTPException(404, "Message not found.")
    return {"ok": True}


# ---------- manager ----------
@router.get("/api/manager/overview")
def manager_overview(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    require(("manager",), authorization, x_session_token)
    people = guidance.list_residents()
    con = get_db()
    pending_updates = con.execute("SELECT COUNT(*) FROM family_updates WHERE status = 'draft'").fetchone()[0]
    sent_updates = con.execute("SELECT COUNT(*) FROM family_updates WHERE status = 'sent'").fetchone()[0]
    unread = con.execute("SELECT COUNT(*) FROM family_messages WHERE read_by IS NULL").fetchone()[0]
    last_sent = {
        r["resident_id"]: r["sent_at"]
        for r in con.execute(
            "SELECT resident_id, MAX(sent_at) AS sent_at FROM family_updates WHERE status = 'sent' GROUP BY resident_id"
        ).fetchall()
    }
    con.close()

    rows, tasks_total, concerns_total = [], 0, 0
    for p in people:
        rec = today_records(p["resident_id"])
        done = sum(1 for t in rec["tasks"] if t["status"] == "given")
        tasks_total += len(rec["tasks"])
        concerns_total += len(rec["concerns"])
        rows.append({
            "resident_id": p["resident_id"],
            "name": p["name"],
            "room": f"Room {100 + p['resident_id']}",
            "tasks": f"{done} done / {len(rec['tasks'])} recorded",
            "concerns": len(rec["concerns"]),
            "family_update": ("Sent " + last_sent[p["resident_id"]][11:16]) if p["resident_id"] in last_sent else "Not sent today",
        })

    try:
        pending_guidance = len(db.list_drafts("draft"))
    except Exception:
        pending_guidance = 0

    staff = auth.list_users()
    kpis = [
        {"label": "Residents", "value": len(people), "sub": "in the home"},
        {"label": "Care records today", "value": tasks_total, "sub": "tasks logged by carers"},
        {"label": "Concerns today", "value": concerns_total, "sub": "raised to the nurse", "alert": concerns_total > 0},
        {"label": "Waiting for a nurse", "value": pending_guidance + pending_updates, "sub": "AI drafts to approve", "alert": (pending_guidance + pending_updates) > 0},
        {"label": "Family updates sent", "value": sent_updates, "sub": f"{unread} unread family message(s)"},
        {"label": "User accounts", "value": len(staff), "sub": "carers, nurses, managers, families"},
    ]
    return {"kpis": kpis, "residents": rows, "audit": db.audit_entries(40)}


@router.get("/api/manager/users")
def manager_users(authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    require(("manager",), authorization, x_session_token)
    return auth.list_users()


@router.post("/api/manager/users", status_code=201)
def manager_create_user(
    body: CreateUserRequest,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("manager",), authorization, x_session_token)
    if body.role == "family":
        resident_or_404(body.resident_id or 0)
    try:
        user = auth.register_user(body.username, body.password, body.full_name, body.role, body.resident_id)
    except ValueError as err:
        raise HTTPException(400, str(err))
    audit(sess["full_name"], "manager", "user_created", user["resident_id"], f"{user['username']} ({user['role']})")
    return user


@router.delete("/api/manager/users/{username}")
def manager_delete_user(
    username: str,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    sess = require(("manager",), authorization, x_session_token)
    if username.strip().lower() == sess["username"]:
        raise HTTPException(400, "You cannot remove your own account.")
    if not auth.delete_user(username):
        raise HTTPException(404, "User not found.")
    audit(sess["full_name"], "manager", "user_removed", None, username)
    return {"ok": True}

