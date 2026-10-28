"""User authentication, registration, session management, and role-based access for Nurse, Carer, and Patient."""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

DB_PATH = Path(os.getenv("AGECARE_DB") or Path(__file__).resolve().parent.parent / "data" / "agecare.db")

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    resident_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    full_name TEXT NOT NULL,
    resident_id INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS patient_wellbeing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    sentiment TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_call_bell (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    resident_name TEXT NOT NULL,
    request_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
"""


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_auth_db() -> None:
    """Initialize auth tables, run column migrations if needed, and seed default users."""
    with _get_connection() as conn:
        conn.executescript(AUTH_SCHEMA)
        
        # Safe migration: ensure resident_id column exists in existing tables
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        cols = [r["name"] for r in cur.fetchall()]
        if "resident_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN resident_id INTEGER")
            
        cur.execute("PRAGMA table_info(user_sessions)")
        s_cols = [r["name"] for r in cur.fetchall()]
        if "resident_id" not in s_cols:
            conn.execute("ALTER TABLE user_sessions ADD COLUMN resident_id INTEGER")

        # Safe migration: update CHECK constraint on users if created with older nurse/carer-only check
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        table_row = cur.fetchone()
        if table_row and "CHECK" in (table_row["sql"] or "") and "'patient'" not in (table_row["sql"] or ""):
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("""
                CREATE TABLE users_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('nurse', 'carer', 'patient')),
                    resident_id INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO users_temp (id, username, password_hash, salt, full_name, role, resident_id, created_at)
                SELECT id, username, password_hash, salt, full_name, role, resident_id, created_at FROM users
            """)
            conn.execute("DROP TABLE users")
            conn.execute("ALTER TABLE users_temp RENAME TO users")
            conn.execute("PRAGMA foreign_keys = ON")

        # Seed default accounts if users are empty or patient1 is missing
        cur.execute("SELECT * FROM users WHERE username = 'patient1'")
        if not cur.fetchone():
            _seed_user(conn, "patient1", "password123", "Margaret Taylor (Resident, Room 102)", "patient", 1)

        cur.execute("SELECT * FROM users WHERE username = 'nurse1'")
        if not cur.fetchone():
            _seed_user(conn, "nurse1", "password123", "Nurse Sarah Johnson (RN)", "nurse", None)

        cur.execute("SELECT * FROM users WHERE username = 'carer1'")
        if not cur.fetchone():
            _seed_user(conn, "carer1", "password123", "Carer Priya Patel", "carer", None)


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return hashed.hex(), salt


def _seed_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    full_name: str,
    role: str,
    resident_id: int | None = None,
) -> None:
    pwd_hash, salt = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO users (username, password_hash, salt, full_name, role, resident_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (username.lower().strip(), pwd_hash, salt, full_name.strip(), role.strip().lower(), resident_id, now),
    )


def register_user(
    username: str,
    password: str,
    full_name: str,
    role: Literal["nurse", "carer", "patient"],
    resident_id: int | None = None,
) -> dict:
    """Register a new user account with role."""
    clean_user = username.strip().lower()
    if len(clean_user) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if not full_name.strip():
        raise ValueError("Full name is required.")
    if role not in ("nurse", "carer", "patient"):
        raise ValueError("Role must be 'nurse', 'carer', or 'patient'.")

    # If patient, default resident_id to 1 if not specified
    if role == "patient" and resident_id is None:
        resident_id = 1

    pwd_hash, salt = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        with _get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash, salt, full_name, role, resident_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (clean_user, pwd_hash, salt, full_name.strip(), role, resident_id, now),
            )
            user_id = cur.lastrowid
            return {
                "id": user_id,
                "username": clean_user,
                "full_name": full_name.strip(),
                "role": role,
                "resident_id": resident_id,
            }
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{clean_user}' is already taken.")


def authenticate_user(username: str, password: str) -> dict | None:
    """Verify username and password against database."""
    clean_user = username.strip().lower()
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (clean_user,))
        user = cur.fetchone()
        if not user:
            return None

        pwd_hash, _ = _hash_password(password, user["salt"])
        if pwd_hash != user["password_hash"]:
            return None

        return {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "resident_id": user["resident_id"],
        }


def create_session(user: dict) -> dict:
    """Create a new session token valid for 7 days."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, username, role, full_name, resident_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user["id"],
                user["username"],
                user["role"],
                user["full_name"],
                user.get("resident_id"),
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
    return {
        "token": token,
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "resident_id": user.get("resident_id"),
        "expires_at": expires.isoformat(timespec="seconds"),
    }


def get_session(token: str) -> dict | None:
    """Retrieve session if valid and not expired."""
    if not token:
        return None
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_sessions WHERE token = ?", (token.strip(),))
        row = cur.fetchone()
        if not row:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token.strip(),))
            return None

        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "role": row["role"],
            "full_name": row["full_name"],
            "resident_id": row["resident_id"],
        }


def delete_session(token: str) -> None:
    """Log out user by destroying session token."""
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token.strip(),))


# ---------- Patient / Resident Interactive Features ----------
def log_patient_wellbeing(resident_id: int, sentiment: str, note: str = "") -> dict:
    """Save patient sentiment check-in. If in pain or uncomfortable, auto-alert nurse & carer."""
    now = datetime.now().isoformat(timespec="seconds")
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO patient_wellbeing (resident_id, sentiment, note, created_at) VALUES (?, ?, ?, ?)",
            (resident_id, sentiment, note.strip(), now),
        )

        # High priority concern if in discomfort or pain
        if sentiment in ("uncomfortable", "in_pain"):
            concern_type = "Pain" if sentiment == "in_pain" else "Mood or behaviour"
            alert_note = f"Patient self-reported feeling {sentiment.replace('_', ' ')}."
            if note.strip():
                alert_note += f" Resident note: '{note.strip()}'"

            conn.execute(
                """CREATE TABLE IF NOT EXISTS carer_concerns (
                    id INTEGER PRIMARY KEY, resident_id TEXT, type TEXT, note TEXT,
                    carer TEXT, created_at TEXT)"""
            )
            conn.execute(
                "INSERT INTO carer_concerns (resident_id, type, note, carer, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(resident_id), concern_type, alert_note, "Resident Self-Check", now),
            )
    return {"ok": True, "alert_triggered": sentiment in ("uncomfortable", "in_pain")}


def trigger_call_bell(resident_id: int, resident_name: str, request_type: str) -> dict:
    """Save call bell request and immediately notify carers and nurses."""
    now = datetime.now().isoformat(timespec="seconds")
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO patient_call_bell (resident_id, resident_name, request_type, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (resident_id, resident_name, request_type, now),
        )

        # Post to carer concerns so it pops up in the shift feed & nurse triage board
        conn.execute(
            """CREATE TABLE IF NOT EXISTS carer_concerns (
                id INTEGER PRIMARY KEY, resident_id TEXT, type TEXT, note TEXT,
                carer TEXT, created_at TEXT)"""
        )
        conn.execute(
            "INSERT INTO carer_concerns (resident_id, type, note, carer, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(resident_id), "Other", f"🔔 CALL BELL: {resident_name} requested assistance ({request_type})", "Bedside Call Bell", now),
        )
    return {"ok": True, "status": "sent"}
