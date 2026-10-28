"""User authentication, registration, session management, and role-based access."""
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
    role TEXT NOT NULL CHECK (role IN ('nurse', 'carer')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    full_name TEXT NOT NULL,
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
    """Initialize auth tables and seed default users if not present."""
    with _get_connection() as conn:
        conn.executescript(AUTH_SCHEMA)
        
        # Check if any users exist; if not, seed default accounts
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM users")
        if cur.fetchone()["count"] == 0:
            _seed_user(conn, "nurse1", "password123", "Nurse Sarah Johnson (RN)", "nurse")
            _seed_user(conn, "carer1", "password123", "Carer Priya Patel", "carer")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return hashed.hex(), salt


def _seed_user(conn: sqlite3.Connection, username: str, password: str, full_name: str, role: str) -> None:
    pwd_hash, salt = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO users (username, password_hash, salt, full_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (username.lower().strip(), pwd_hash, salt, full_name.strip(), role.strip().lower(), now),
    )


def register_user(username: str, password: str, full_name: str, role: Literal["nurse", "carer"]) -> dict:
    """Register a new user account with role."""
    clean_user = username.strip().lower()
    if len(clean_user) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if not full_name.strip():
        raise ValueError("Full name is required.")
    if role not in ("nurse", "carer"):
        raise ValueError("Role must be either 'nurse' or 'carer'.")

    pwd_hash, salt = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        with _get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash, salt, full_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (clean_user, pwd_hash, salt, full_name.strip(), role, now),
            )
            user_id = cur.lastrowid
            return {
                "id": user_id,
                "username": clean_user,
                "full_name": full_name.strip(),
                "role": role,
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
        }


def create_session(user: dict) -> dict:
    """Create a new session token valid for 7 days."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, username, role, full_name, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user["id"],
                user["username"],
                user["role"],
                user["full_name"],
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
    return {
        "token": token,
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
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
        }


def delete_session(token: str) -> None:
    """Log out user by destroying session token."""
    if not token:
        return
    with _get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token.strip(),))
