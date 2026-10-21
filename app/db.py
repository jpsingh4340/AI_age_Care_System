"""A small SQLite database (one file, built into Python) for drafts and the audit log."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("AGECARE_DB") or Path(__file__).resolve().parent.parent / "data" / "agecare.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS guidance_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,          -- draft, approved, rejected, replaced
    content TEXT NOT NULL,         -- the lines and sources, as JSON
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_note TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    report_date TEXT NOT NULL,
    checked_by TEXT NOT NULL,
    saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    resident_id INTEGER,
    draft_id INTEGER,
    detail TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def session():
    """Open the database, save the changes when the block ends, then close it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)  # creates the tables the first time
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _audit(conn, actor, role, action, resident_id, draft_id, detail):
    conn.execute(
        "INSERT INTO audit_log (at, actor, role, action, resident_id, draft_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now(), actor, role, action, resident_id, draft_id, detail),
    )


def _draft_from_row(row) -> dict:
    return {
        "draft_id": row["id"],
        "resident_id": row["resident_id"],
        "created_at": row["created_at"],
        "model": row["model"],
        "status": row["status"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        **json.loads(row["content"]),
    }


def save_draft(resident_id: int, model: str, content: dict) -> int:
    with session() as conn:
        cursor = conn.execute(
            "INSERT INTO guidance_drafts (resident_id, created_at, model, status, content) "
            "VALUES (?, ?, ?, 'draft', ?)",
            (resident_id, now(), model, json.dumps(content)),
        )
        draft_id = cursor.lastrowid
        kept = len(content["watch_for"]) + len(content["prevention"])
        _audit(
            conn, model, "ai", "draft_created", resident_id, draft_id,
            f"{kept} lines kept, {len(content['dropped'])} removed by the automatic check",
        )
        return draft_id


def get_draft(draft_id: int) -> dict | None:
    with session() as conn:
        row = conn.execute("SELECT * FROM guidance_drafts WHERE id = ?", (draft_id,)).fetchone()
    return _draft_from_row(row) if row else None


def list_drafts(status: str = "draft") -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT * FROM guidance_drafts WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()
    return [_draft_from_row(row) for row in rows]


def latest_approved(resident_id: int) -> dict | None:
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM guidance_drafts WHERE resident_id = ? AND status = 'approved' "
            "ORDER BY id DESC LIMIT 1",
            (resident_id,),
        ).fetchone()
    return _draft_from_row(row) if row else None


def decide(draft_id: int, decision: str, reviewer: str, note: str, content: dict, detail: str) -> None:
    """Record a nurse's decision. Raises LookupError or ValueError if it cannot be recorded."""
    with session() as conn:
        row = conn.execute("SELECT * FROM guidance_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise LookupError("Draft not found.")
        if row["status"] != "draft":
            raise ValueError("This draft was already decided.")

        status = "approved" if decision == "approve" else "rejected"
        if status == "approved":  # only one approved version per resident is live
            conn.execute(
                "UPDATE guidance_drafts SET status = 'replaced' "
                "WHERE resident_id = ? AND status = 'approved'",
                (row["resident_id"],),
            )
        conn.execute(
            "UPDATE guidance_drafts SET status = ?, content = ?, reviewed_by = ?, "
            "reviewed_at = ?, review_note = ? WHERE id = ?",
            (status, json.dumps(content), reviewer, now(), note, draft_id),
        )
        _audit(conn, reviewer, "nurse", status, row["resident_id"], draft_id, detail)


def audit_entries(limit: int = 50) -> list[dict]:
    with session() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


    

def save_readings(resident_id: int, reviewer: str, report_date: str, items: list[dict]) -> int:
    """Save values a nurse has checked. Each item has key, label, value and unit."""
    with session() as conn:
        for item in items:
            conn.execute(
                "INSERT INTO readings (resident_id, key, label, value, unit, report_date, checked_by, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (resident_id, item["key"], item["label"], item["value"], item["unit"], report_date, reviewer, now()),
            )
        names = ", ".join(item["label"] for item in items)
        _audit(
            conn, reviewer, "nurse", "readings_saved", resident_id, None,
            f"{len(items)} values checked and saved: {names}. Report date: {report_date or 'not given'}.",
        )
    return len(items)


def list_readings(resident_id: int) -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT * FROM readings WHERE resident_id = ? ORDER BY id DESC", (resident_id,)
        ).fetchall()
    return [dict(row) for row in rows]