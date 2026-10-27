# Carer page - carers record tasks, vitals and concerns for a resident.
# Saves into its own tables in the same sqlite db.
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "static"
DB_PATH = getattr(config, "DB_PATH", BASE_DIR / "data" / "agecare.db")

TASKS = ["Offer a drink", "Breakfast eaten", "Lunch eaten", "Dinner eaten",
         "Help to change position", "Help to the toilet", "Shower or wash", "Walk with frame"]
CONCERN_TYPES = ["Fall or near fall", "Not eating", "Not drinking", "Skin change",
                 "Pain", "Mood or behaviour", "Other"]


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS carer_tasks (
        id INTEGER PRIMARY KEY, resident_id TEXT, task TEXT, status TEXT,
        carer TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS carer_vitals (
        id INTEGER PRIMARY KEY, resident_id TEXT, pulse INTEGER, systolic INTEGER,
        diastolic INTEGER, temperature REAL, spo2 INTEGER, carer TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS carer_concerns (
        id INTEGER PRIMARY KEY, resident_id TEXT, type TEXT, note TEXT,
        carer TEXT, created_at TEXT)""")
    return con


def save(sql, args):
    con = get_db()
    con.execute(sql, args)
    con.commit()
    con.close()


def now():
    return datetime.now().isoformat(timespec="seconds")


class TaskIn(BaseModel):
    resident_id: str
    task: str = Field(min_length=2, max_length=60)
    status: Literal["given", "refused", "not_done"]
    carer: str = Field(min_length=2, max_length=40)


class VitalsIn(BaseModel):
    resident_id: str
    pulse: int | None = Field(None, ge=30, le=200)
    systolic: int | None = Field(None, ge=60, le=250)
    diastolic: int | None = Field(None, ge=30, le=150)
    temperature: float | None = Field(None, ge=34, le=42)
    spo2: int | None = Field(None, ge=70, le=100)
    carer: str = Field(min_length=2, max_length=40)


class ConcernIn(BaseModel):
    resident_id: str
    type: str
    note: str = Field(min_length=3, max_length=300)
    carer: str = Field(min_length=2, max_length=40)


@router.get("/carer", include_in_schema=False)
def carer_page():
    return FileResponse(STATIC_DIR / "carer.html")


@router.get("/api/carer/options")
def options():
    return {"tasks": TASKS, "concern_types": CONCERN_TYPES}


@router.post("/api/carer/tasks", status_code=201)
def add_task(body: TaskIn):
    save("INSERT INTO carer_tasks (resident_id, task, status, carer, created_at) VALUES (?, ?, ?, ?, ?)",
         (body.resident_id, body.task, body.status, body.carer, now()))
    return {"ok": True}


@router.post("/api/carer/vitals", status_code=201)
def add_vitals(body: VitalsIn):
    values = [body.pulse, body.systolic, body.diastolic, body.temperature, body.spo2]
    if all(v is None for v in values):
        raise HTTPException(400, "Enter at least one number")
    save("""INSERT INTO carer_vitals (resident_id, pulse, systolic, diastolic, temperature, spo2, carer, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
         (body.resident_id, *values, body.carer, now()))
    # simple check against usual ranges, not a risk score
    tell_nurse = ((body.pulse is not None and not 50 <= body.pulse <= 100)
                  or (body.temperature is not None and not 36.0 <= body.temperature <= 37.8)
                  or (body.spo2 is not None and body.spo2 < 94)
                  or (body.systolic is not None and not 100 <= body.systolic <= 160))
    return {"ok": True, "tell_nurse": tell_nurse}


@router.post("/api/carer/concerns", status_code=201)
def add_concern(body: ConcernIn):
    if body.type not in CONCERN_TYPES:
        raise HTTPException(400, "Pick a concern type from the list")
    save("INSERT INTO carer_concerns (resident_id, type, note, carer, created_at) VALUES (?, ?, ?, ?, ?)",
         (body.resident_id, body.type, body.note, body.carer, now()))
    return {"ok": True}


@router.get("/api/carer/today")
def today(resident_id: str | None = None):
    # everything recorded today, for one resident or for all of them
    day = datetime.now().date().isoformat() + "%"
    out = {}
    con = get_db()
    for name in ["tasks", "vitals", "concerns"]:
        sql = f"SELECT * FROM carer_{name} WHERE created_at LIKE ?"
        args = [day]
        if resident_id:
            sql += " AND resident_id = ?"
            args.append(resident_id)
        rows = con.execute(sql + " ORDER BY created_at DESC", args).fetchall()
        out[name] = [dict(r) for r in rows]
    con.close()
    return out