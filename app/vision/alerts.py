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


def list_alerts(open_only=False, limit=50):
    sql = "SELECT * FROM vision_alerts"
    if open_only:
        sql += " WHERE outcome IS NULL"
    sql += " ORDER BY id DESC LIMIT ?"
    with db.session() as conn:
        conn.execute(TABLE)
        rows = conn.execute(sql, (limit,)).fetchall()
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