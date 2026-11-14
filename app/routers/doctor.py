# Doctor summary PDF (user stories #3, #5 and #6).
#
#   1. Prepare   the nurse builds a summary from the resident's records in a fixed layout.
#                No AI writes clinical facts. The only AI text is a shift handover that a
#                nurse already approved, and it is labelled "AI draft".
#   2. Review    the nurse previews it, corrects lines or leaves them out, then marks it reviewed.
#   3. Send      a separate button, only after review. Sending is simulated: the nurse downloads
#                the PDF and no doctor is contacted.
#   Each step is written to the audit log with the person and the time.
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app import decision, records
from app.decision_rules import check_vitals
from app.pdf_simple import make_pdf
from app.routers import handover, portal

router = APIRouter(tags=["Doctor summary"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
STATUS_TEXT = {"given": "done", "refused": "refused", "not_done": "not done"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctor_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | reviewed | sent
    content TEXT NOT NULL,                  -- JSON, see build_content()
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    sent_by TEXT,
    sent_at TEXT,
    sent_to TEXT
);
"""


def get_db() -> sqlite3.Connection:
    con = handover.get_db()
    con.executescript(SCHEMA)
    return con


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def nurse(authorization: str, x_session_token: str) -> dict:
    return portal.require(("nurse",), authorization, x_session_token)


def line(text: str, source: str = "") -> dict:
    return {"text": text, "include": True, "edited": False, "original": text, "source": source}


# ---------- building the summary from the records ----------
def build_content(resident_id: int) -> dict:
    """Everything the doctor needs, from the records only. The same content makes the preview and the PDF."""
    rec = records.build_records(resident_id)
    if rec is None:
        raise HTTPException(404, "Resident not found.")

    # vital signs: the fake history plus anything carers recorded, newest of each
    history = {key: [p.model_dump() for p in values] for key, values in rec.readings_history.items()}
    extra, _ = decision._carer_page_entries(resident_id)
    for key, values in extra.items():
        history.setdefault(key, []).extend(values)
    vitals = [line(f"{v['reason']} Level: {v['level']}.", v["source"]) for v in check_vitals(history)]

    care = [line(f"{c.time}  {c.task}: {STATUS_TEXT.get(c.status, c.status)}", f"Recorded by {c.by}")
            for c in sorted(rec.care_record, key=lambda c: c.time)]
    concerns = [line(f"{c.time}  {c.type}: {c.text}", "Carer concern") for c in rec.concerns]
    contacts = [line(f"{c.name} ({c.relationship}): {c.phone}") for c in rec.contacts]

    sections = [
        {"key": "vitals", "title": "Recent vital signs", "label": "Latest reading of each, checked against NZEWS rules", "lines": vitals},
        {"key": "care", "title": "Today's care", "label": "", "lines": care},
        {"key": "concerns", "title": "Concerns raised by carers", "label": "", "lines": concerns},
    ]

    # the latest handover a nurse approved in the last 24 hours (the only AI-drafted text)
    con = handover.get_db()
    row = con.execute(
        "SELECT * FROM handovers WHERE resident_id = ? AND status = 'approved' AND reviewed_at >= ? ORDER BY reviewed_at DESC LIMIT 1",
        (resident_id, (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")),
    ).fetchone()
    con.close()
    if row:
        sections.append({
            "key": "handover",
            "title": "Latest shift handover",
            "label": f"AI draft, checked and approved by {row['reviewed_by']} at {row['reviewed_at'][11:16]}",
            "lines": [line(t) for t in row["text"].split("\n") if t.strip()],
        })

    sections.append({"key": "contacts", "title": "Family contacts", "label": "", "lines": contacts})

    return {
        "resident": {
            "name": rec.name,
            "room": f"Room {100 + resident_id}",
            "conditions": rec.conditions,
            "allergies": rec.allergies or ["None recorded"],
            "date_of_summary": datetime.now().strftime("%d %b %Y"),
        },
        "doctor": {"name": rec.doctor.name, "practice": rec.doctor.practice, "phone": rec.doctor.phone},
        "sections": sections,
        "nurse_note": "",
    }


def summary_out(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["content"] = json.loads(out["content"])
    return out


def get_summary(con: sqlite3.Connection, summary_id: int) -> sqlite3.Row:
    row = con.execute("SELECT * FROM doctor_summaries WHERE id = ?", (summary_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Summary not found.")
    return row


def pdf_blocks(summary: dict) -> list[tuple]:
    """The fixed layout. The browser preview shows the same parts in the same order."""
    c = summary["content"]
    r, doc = c["resident"], c["doctor"]
    status = summary["status"]
    blocks = [
        ("title", "Doctor summary"),
        ("banner", "DEMO DATA ONLY. Fake resident. Student prototype, not a medical record."),
    ]
    if status == "draft":
        blocks.append(("banner", "DRAFT: not yet reviewed by a nurse. Do not send."))
    blocks += [
        ("rule",),
        ("label", f"{r['name']}, {r['room']}"),
        ("text", f"Summary date: {r['date_of_summary']}"),
        ("text", f"To: {doc['name']}, {doc['practice']}. Phone {doc['phone']}"),
        ("label", "Allergies: " + ", ".join(r["allergies"])),
        ("text", "Conditions: " + (", ".join(r["conditions"]) or "None recorded")),
        ("rule",),
    ]
    for section in c["sections"]:
        kept = [ln for ln in section["lines"] if ln["include"]]
        if not kept:
            continue
        blocks.append(("h2", section["title"]))
        if section.get("label"):
            blocks.append(("small", section["label"]))
        for ln in kept:
            blocks.append(("text", "- " + ln["text"] + ("  (corrected by nurse)" if ln["edited"] else ""), 8))
            if ln.get("source"):
                blocks.append(("small", ln["source"], 18))
    if c.get("nurse_note"):
        blocks += [("h2", "Note from the nurse"), ("text", c["nurse_note"])]
    blocks.append(("rule",))
    when = lambda iso: iso.replace("T", " ")[:16]
    blocks.append(("small", f"Prepared by {summary['prepared_by']} at {when(summary['prepared_at'])}."))
    if summary.get("reviewed_by"):
        blocks.append(("small", f"Reviewed by {summary['reviewed_by']} at {when(summary['reviewed_at'])}."))
    if summary.get("sent_by"):
        blocks.append(("small", f"Sent by {summary['sent_by']} at {when(summary['sent_at'])} (simulated: no doctor was contacted)."))
    blocks.append(("small", "Facts come from the care records. The only AI text is the shift handover, labelled as an AI draft and approved by a nurse."))
    return blocks


# ---------- pages ----------
@router.get("/nurse/doctor-summary", include_in_schema=False)
@router.get("/doctor-summary", include_in_schema=False)  # short link used by the navbar and Reports page
def doctor_summary_page():
    return FileResponse(STATIC_DIR / "doctor-summary.html")


# ---------- API ----------
class PrepareIn(BaseModel):
    resident_id: int


class LineEdit(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    include: bool = True


class SectionEdit(BaseModel):
    key: str
    lines: list[LineEdit]


class SummaryEdit(BaseModel):
    sections: list[SectionEdit]
    nurse_note: str = Field(default="", max_length=1000)


@router.post("/api/doctor-summaries", status_code=201)
def prepare(body: PrepareIn, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Step 1: build a new summary from the records."""
    sess = nurse(authorization, x_session_token)
    content = build_content(body.resident_id)
    con = get_db()
    with con:
        cur = con.execute(
            "INSERT INTO doctor_summaries (resident_id, status, content, prepared_by, prepared_at) VALUES (?, 'draft', ?, ?, ?)",
            (body.resident_id, json.dumps(content), sess["full_name"], now()),
        )
        row = get_summary(con, cur.lastrowid)
    con.close()
    portal.audit(sess["full_name"], "nurse", "doctor_summary_prepared", body.resident_id, f"summary #{row['id']}")
    return summary_out(row)


@router.get("/api/doctor-summaries")
def list_summaries(
    resident_id: int | None = None,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    nurse(authorization, x_session_token)
    sql, args = "SELECT * FROM doctor_summaries", []
    if resident_id is not None:
        sql += " WHERE resident_id = ?"
        args.append(resident_id)
    con = get_db()
    rows = con.execute(sql + " ORDER BY id DESC LIMIT 20", args).fetchall()
    con.close()
    return [summary_out(r) for r in rows]


@router.get("/api/doctor-summaries/{summary_id}")
def one_summary(summary_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    nurse(authorization, x_session_token)
    con = get_db()
    row = get_summary(con, summary_id)
    con.close()
    return summary_out(row)


@router.put("/api/doctor-summaries/{summary_id}")
def correct(
    summary_id: int,
    body: SummaryEdit,
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Step 2: the nurse corrects lines or leaves them out. A reviewed summary goes back to draft."""
    sess = nurse(authorization, x_session_token)
    con = get_db()
    row = get_summary(con, summary_id)
    if row["status"] == "sent":
        con.close()
        raise HTTPException(409, "This summary was already sent. Prepare a new one.")
    content = json.loads(row["content"])
    edits = {s.key: s.lines for s in body.sections}
    for section in content["sections"]:
        new_lines = edits.get(section["key"])
        if new_lines is None:
            continue
        if len(new_lines) != len(section["lines"]):
            con.close()
            raise HTTPException(422, f"The {section['title']} section changed. Reload the summary.")
        for ln, new in zip(section["lines"], new_lines):
            ln["text"] = new.text.strip()
            ln["include"] = new.include
            ln["edited"] = ln["text"] != ln["original"]
    content["nurse_note"] = body.nurse_note.strip()
    was_reviewed = row["status"] == "reviewed"
    with con:
        con.execute(
            "UPDATE doctor_summaries SET content = ?, status = 'draft', reviewed_by = NULL, reviewed_at = NULL WHERE id = ?",
            (json.dumps(content), summary_id),
        )
        row = get_summary(con, summary_id)
    con.close()
    if was_reviewed:
        portal.audit(sess["full_name"], "nurse", "doctor_summary_changed", row["resident_id"],
                     f"summary #{summary_id} changed after review, needs reviewing again")
    return summary_out(row)


@router.post("/api/doctor-summaries/{summary_id}/review")
def review(summary_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Step 2 done: the nurse has checked the preview."""
    sess = nurse(authorization, x_session_token)
    con = get_db()
    row = get_summary(con, summary_id)
    if row["status"] != "draft":
        con.close()
        raise HTTPException(409, "Only a draft summary can be reviewed.")
    with con:
        con.execute(
            "UPDATE doctor_summaries SET status = 'reviewed', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (sess["full_name"], now(), summary_id),
        )
        row = get_summary(con, summary_id)
    con.close()
    portal.audit(sess["full_name"], "nurse", "doctor_summary_reviewed", row["resident_id"], f"summary #{summary_id}")
    return summary_out(row)


@router.post("/api/doctor-summaries/{summary_id}/send")
def send(summary_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Step 3: only after review, and only when the nurse presses Send. Simulated: nothing leaves the computer."""
    sess = nurse(authorization, x_session_token)
    con = get_db()
    row = get_summary(con, summary_id)
    if row["status"] == "sent":
        con.close()
        raise HTTPException(409, "This summary was already sent.")
    if row["status"] != "reviewed":
        con.close()
        raise HTTPException(409, "Preview and mark the summary as reviewed before sending.")
    doctor = json.loads(row["content"])["doctor"]
    sent_to = f"{doctor['name']} (simulated: download only)"
    with con:
        con.execute(
            "UPDATE doctor_summaries SET status = 'sent', sent_by = ?, sent_at = ?, sent_to = ? WHERE id = ?",
            (sess["full_name"], now(), sent_to, summary_id),
        )
        row = get_summary(con, summary_id)
    con.close()
    portal.audit(sess["full_name"], "nurse", "doctor_summary_sent", row["resident_id"],
                 f"summary #{summary_id} to {sent_to}. No doctor was contacted.")
    return summary_out(row)


@router.get("/api/doctor-summaries/{summary_id}/pdf")
def pdf(summary_id: int, authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """The PDF, built from the same content as the preview. Drafts say DRAFT on the page."""
    nurse(authorization, x_session_token)
    con = get_db()
    row = get_summary(con, summary_id)
    con.close()
    summary = summary_out(row)
    name = summary["content"]["resident"]["name"]
    data = make_pdf(pdf_blocks(summary), footer=f"AgeCare doctor summary #{summary_id}, {name}. Demo data only.")
    filename = f"doctor-summary-{summary_id}-{summary['status']}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
