"""User authentication, registration, session management, and role-based access.

Four roles, each with its own login and its own page:
  carer   -> /carer    record tasks, vitals and concerns
  nurse   -> /nurse    review, approve guidance and family updates
  manager -> /manager  overview, staff accounts, audit log
  family  -> /family   nurse-approved updates for one resident only
"""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

DB_PATH = Path(os.getenv("AGECARE_DB") or Path(__file__).resolve().parent.parent / "data" / "agecare.db")

ROLES = ("carer", "nurse", "manager", "family")
HOME_PAGE = {"carer": "/carer", "nurse": "/nurse", "manager": "/manager", "family": "/family"}

# username, full name, role, linked resident (family only). Password for all: password123
DEMO_USERS = [
    ("carer1", "Carer Priya Patel", "carer", None),
    ("nurse1", "Nurse Sarah Johnson (RN)", "nurse", None),
    ("manager1", "Tom Baker (Manager)", "manager", None),
    ("family1", "Claire Taylor (Margaret's daughter)", "family", 1),
]

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

        # Safe migration: older databases had a CHECK constraint that only allowed the old roles.
        # Rebuild the table without it - roles are validated in Python (see ROLES).
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        table_row = cur.fetchone()
        if table_row and "CHECK" in (table_row["sql"] or ""):
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DROP TABLE IF EXISTS users_temp")
            conn.execute("""
                CREATE TABLE users_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
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

        # The bedside "patient" role was replaced by the Family portal - remove old patient logins.
        conn.execute("DELETE FROM user_sessions WHERE role NOT IN ('nurse', 'carer', 'manager', 'family')")
        conn.execute("DELETE FROM users WHERE role NOT IN ('nurse', 'carer', 'manager', 'family')")

        # Seed one demo account per role (all fake people)
        for username, full_name, role, resident_id in DEMO_USERS:
            cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            if not cur.fetchone():
                _seed_user(conn, username, "password123", full_name, role, resident_id)


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
    role: Literal["carer", "nurse", "manager", "family"],
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
    if role not in ROLES:
        raise ValueError("Role must be carer, nurse, manager or family.")

    # A family login can only ever see one resident, so it must be linked to one.
    if role == "family" and not resident_id:
        raise ValueError("Pick the resident this family member is linked to.")
    if role != "family":
        resident_id = None

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
    """Verify username or email and password against database."""
    clean_user = username.strip().lower()
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (clean_user,))
        user = cur.fetchone()
        if not user and "@" in clean_user:
            prefix = clean_user.split("@", 1)[0]
            cur.execute("SELECT * FROM users WHERE username = ?", (prefix,))
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


# ---------- Helpers used by the role pages ----------
def token_from_headers(authorization: str = "", x_session_token: str = "") -> str:
    """Read the session token from the X-Session-Token or Authorization: Bearer header."""
    if isinstance(x_session_token, str) and x_session_token.strip():
        return x_session_token.strip()
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return ""


def session_from_headers(authorization: str = "", x_session_token: str = "") -> dict | None:
    """The signed-in user for this request, or None."""
    token = token_from_headers(authorization, x_session_token)
    return get_session(token) if token else None


def list_users() -> list[dict]:
    """All accounts (no password data) - for the manager page."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, full_name, role, resident_id, created_at FROM users ORDER BY role, username"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_user(username: str) -> bool:
    """Remove an account and its sessions. Returns False if it did not exist."""
    with _get_connection() as conn:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username.strip().lower(),))
        conn.execute("DELETE FROM user_sessions WHERE username = ?", (username.strip().lower(),))
        return cur.rowcount > 0



def firebase_sync_user(
    email: str,
    full_name: str = "",
    role: str = "carer",
    resident_id: int | None = None,
) -> dict:
    """Verify that a Firebase/Google email is already registered, and return its assigned role."""
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email address is required.")

    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (clean_email,))
        user = cur.fetchone()
        if not user:
            raise ValueError(f"Account '{clean_email}' is not registered. Please sign up first.")

        return {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "resident_id": user["resident_id"],
        }
