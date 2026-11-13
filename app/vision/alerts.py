"""Feature C: alerts for the nurse, kept in the team database.

An alert is text and numbers only: what was seen, when, where, and the
nurse's decision. No photo or video frame is ever stored.

Every new alert and every nurse decision also goes into the team's audit log.
"""

from app import db

# What a nurse can decide after checking the resident.
OUTCOMES = {
    "fine": "Checked, the resident is fine.",
    "action_taken": "Checked, and the nurse helped the resident.",
    "false_alarm": "False alarm, nothing happened.",
    "escalated": "Escalated to the doctor or emergency services.",
}
# These outcomes must say what was done.
NOTE_NEEDED = {"action_taken", "escalated"}


class AlreadyDecided(Exception):
    """A nurse has already decided this alert."""


TABLE = """
CREATE TABLE IF NOT EXISTS vision_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,          -- cue_check or room_monitor
    alert_type TEXT NOT NULL,      -- high_cue, possible_fall, no_movement
    resident_id INTEGER,
    camera TEXT,
    confidence REAL,
    message TEXT NOT NULL,
    outcome TEXT,                  -- empty until a nurse decides
    outcome_note TEXT,
    decided_by TEXT,
    decided_at TEXT
)
"""


def add_alert(source, alert_type, message, resident_id=None, camera=None, confidence=None):
    with db.session() as conn:
        conn.execute(TABLE)
        cur = conn.execute(
            "INSERT INTO vision_alerts (created_at, source, alert_type, resident_id, camera, confidence, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (db.now(), source, alert_type, resident_id, camera, confidence, message),
        )
        alert_id = cur.lastrowid
        db._audit(conn, "Feature C", "system", "vision_alert", resident_id, None,
                  f"Alert {alert_id}: {message}")
    return get_alert(alert_id)


def get_alert(alert_id):
    with db.session() as conn:
        conn.execute(TABLE)
        row = conn.execute("SELECT * FROM vision_alerts WHERE id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def list_alerts(open_only=False, limit=50, resident_id=None):
    sql, args = "SELECT * FROM vision_alerts WHERE 1 = 1", []
    if open_only:
        sql += " AND outcome IS NULL"
    if resident_id is not None:
        sql += " AND resident_id = ?"
        args.append(resident_id)
    sql += " ORDER BY id DESC LIMIT ?"
    with db.session() as conn:
        conn.execute(TABLE)
        rows = conn.execute(sql, (*args, limit)).fetchall()
    return [dict(r) for r in rows]

def decide_alert(alert_id, outcome, nurse, note=""):
    """A nurse records what happened after checking the resident."""
    note = (note or "").strip()
    if outcome not in OUTCOMES:
        raise ValueError("Pick one of: " + ", ".join(OUTCOMES))
    if outcome in NOTE_NEEDED and not note:
        raise ValueError("Please write a short note on what was done.")
    alert = get_alert(alert_id)
    if alert is None:
        raise LookupError("There is no alert with that number.")
    if alert["outcome"]:
        raise AlreadyDecided("A nurse has already decided this alert.")

    detail = f"Alert {alert_id}: {OUTCOMES[outcome]}"
    if note:
        detail += f" Note: {note}"
    with db.session() as conn:
        conn.execute(
            "UPDATE vision_alerts SET outcome = ?, outcome_note = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (outcome, note, nurse, db.now(), alert_id),
        )
        db._audit(conn, nurse, "nurse", "vision_decision", alert["resident_id"], None, detail)
    return get_alert(alert_id)

# ---------- follow-ups: the nurse asks a carer to do something after an alert ----------
FOLLOWUP_TABLE = """
CREATE TABLE IF NOT EXISTS vision_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    resident_id INTEGER NOT NULL,
    instruction TEXT NOT NULL,     -- what the nurse wants the carer to do
    sent_by TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    done_by TEXT,                  -- empty until a carer ticks it off
    done_at TEXT,
    done_note TEXT
)
"""


def send_to_carer(alert_id, instruction, nurse):
    """The nurse sends a one-off instruction to the carers for this alert's resident."""
    instruction = (instruction or "").strip()
    if len(instruction) < 5:
        raise ValueError("Write what the carer should do (at least a few words).")
    alert = get_alert(alert_id)
    if alert is None:
        raise LookupError("There is no alert with that number.")
    if alert["resident_id"] is None:
        raise ValueError("This is a practice alert with no resident, so there is no carer to send it to.")
    with db.session() as conn:
        conn.execute(FOLLOWUP_TABLE)
        cur = conn.execute(
            "INSERT INTO vision_followups (alert_id, resident_id, instruction, sent_by, sent_at) VALUES (?, ?, ?, ?, ?)",
            (alert_id, alert["resident_id"], instruction, nurse, db.now()),
        )
        followup_id = cur.lastrowid
        db._audit(conn, nurse, "nurse", "vision_followup_sent", alert["resident_id"], None,
                  f"Alert {alert_id}: asked the carer to: {instruction}")
    return get_followup(followup_id)


def get_followup(followup_id):
    with db.session() as conn:
        conn.execute(FOLLOWUP_TABLE)
        conn.execute(TABLE)
        row = conn.execute(
            "SELECT f.*, a.alert_type, a.message AS alert_message FROM vision_followups f "
            "JOIN vision_alerts a ON a.id = f.alert_id WHERE f.id = ?", (followup_id,)).fetchone()
    return dict(row) if row else None


def list_followups(resident_id=None, alert_id=None, open_only=False):
    sql = ("SELECT f.*, a.alert_type, a.message AS alert_message FROM vision_followups f "
           "JOIN vision_alerts a ON a.id = f.alert_id WHERE 1 = 1")
    args = []
    if resident_id is not None:
        sql += " AND f.resident_id = ?"
        args.append(resident_id)
    if alert_id is not None:
        sql += " AND f.alert_id = ?"
        args.append(alert_id)
    if open_only:
        sql += " AND f.done_at IS NULL"
    sql += " ORDER BY f.id DESC"
    with db.session() as conn:
        conn.execute(FOLLOWUP_TABLE)
        conn.execute(TABLE)
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def complete_followup(followup_id, carer, note=""):
    """A carer ticks off the nurse's instruction, with an optional short note."""
    note = (note or "").strip()
    item = get_followup(followup_id)
    if item is None:
        raise LookupError("There is no follow-up with that number.")
    if item["done_at"]:
        raise AlreadyDecided("This follow-up is already done.")
    with db.session() as conn:
        conn.execute("UPDATE vision_followups SET done_by = ?, done_at = ?, done_note = ? WHERE id = ?",
                     (carer, db.now(), note, followup_id))
        detail = f"Alert {item['alert_id']}: follow-up done. {item['instruction']}"
        if note:
            detail += f" Note: {note}"
        db._audit(conn, carer, "carer", "vision_followup_done", item["resident_id"], None, detail)
    return get_followup(followup_id)
