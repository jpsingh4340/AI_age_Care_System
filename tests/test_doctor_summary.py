"""Doctor summary PDF: prepare, preview and correct, send (simulated), audit. User stories #3, #5, #6."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app
from app.pdf_simple import make_pdf
from app.routers import carer, handover

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(carer, "DB_PATH", test_db)
    monkeypatch.setattr(auth, "DB_PATH", test_db)
    auth.init_auth_db()

    def no_model(system, user, fields=("text",)):
        raise RuntimeError("model off")
    monkeypatch.setattr(handover, "ask_model", no_model)


def login(username):
    token = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def prepare(nurse, resident_id=1):
    r = client.post("/api/doctor-summaries", json={"resident_id": resident_id}, headers=nurse)
    assert r.status_code == 201
    return r.json()


def section(summary, key):
    return next(s for s in summary["content"]["sections"] if s["key"] == key)


def edits(summary, change=None):
    """The current lines of every section, optionally changed by change(key, index, line)."""
    out = []
    for s in summary["content"]["sections"]:
        lines = []
        for i, ln in enumerate(s["lines"]):
            item = {"text": ln["text"], "include": ln["include"]}
            if change:
                change(s["key"], i, item)
            lines.append(item)
        out.append({"key": s["key"], "lines": lines})
    return out


def test_only_a_nurse_can_prepare():
    assert client.post("/api/doctor-summaries", json={"resident_id": 1}, headers=login("carer1")).status_code == 403
    assert client.post("/api/doctor-summaries", json={"resident_id": 1}).status_code == 401


def test_summary_is_built_from_the_records_in_a_fixed_layout():
    s = prepare(login("nurse1"))
    c = s["content"]
    assert s["status"] == "draft"
    assert c["resident"]["name"] == "Margaret T." and c["resident"]["allergies"] == ["Peanuts"]
    assert c["doctor"]["name"] == "Dr Example Smith"
    assert [x["key"] for x in c["sections"]] == ["vitals", "care", "concerns", "contacts"]
    # every vital sign line comes from the rules, with its date
    assert all(ln["source"].startswith("Vital signs record") for ln in section(s, "vitals")["lines"])
    assert any("Only had a few sips" in ln["text"] for ln in section(s, "concerns")["lines"])


def test_cannot_send_before_review_and_send_is_simulated():
    nurse = login("nurse1")
    s = prepare(nurse)
    assert client.post(f"/api/doctor-summaries/{s['id']}/send", headers=nurse).status_code == 409
    client.post(f"/api/doctor-summaries/{s['id']}/review", headers=nurse)
    sent = client.post(f"/api/doctor-summaries/{s['id']}/send", headers=nurse).json()
    assert sent["status"] == "sent" and "simulated" in sent["sent_to"]
    assert client.post(f"/api/doctor-summaries/{s['id']}/send", headers=nurse).status_code == 409
    # a sent summary cannot be changed
    assert client.put(f"/api/doctor-summaries/{s['id']}", json={"sections": edits(sent)}, headers=nurse).status_code == 409


def test_corrections_and_left_out_lines_reach_the_pdf():
    nurse = login("nurse1")
    s = prepare(nurse)

    def change(key, i, item):
        if key == "concerns" and i == 0:
            item["text"] = "12:45  Low fluids: drank half a cup of tea at lunch."
        if key == "contacts":
            item["include"] = False
    fixed = client.put(f"/api/doctor-summaries/{s['id']}", json={"sections": edits(s, change), "nurse_note": "Please review fluids."}, headers=nurse).json()
    first = section(fixed, "concerns")["lines"][0]
    assert first["edited"] is True and first["original"].endswith("Only had a few sips of tea at lunch.")

    pdf = client.get(f"/api/doctor-summaries/{s['id']}/pdf", headers=nurse)
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert b"drank half a cup of tea" in pdf.content and b"corrected by nurse" in pdf.content
    assert b"Please review fluids." in pdf.content
    assert b"Anna T." not in pdf.content       # the left-out contact
    assert b"Peanuts" in pdf.content            # allergies are always shown
    assert b"DRAFT: not yet reviewed" in pdf.content


def test_changing_a_reviewed_summary_needs_review_again():
    nurse = login("nurse1")
    s = prepare(nurse)
    client.post(f"/api/doctor-summaries/{s['id']}/review", headers=nurse)
    changed = client.put(f"/api/doctor-summaries/{s['id']}", json={"sections": edits(s), "nurse_note": "Added later."}, headers=nurse).json()
    assert changed["status"] == "draft" and changed["reviewed_by"] is None
    assert client.post(f"/api/doctor-summaries/{s['id']}/send", headers=nurse).status_code == 409


def test_every_step_is_in_the_audit_log_with_the_person():
    nurse = login("nurse1")
    s = prepare(nurse)
    client.post(f"/api/doctor-summaries/{s['id']}/review", headers=nurse)
    client.post(f"/api/doctor-summaries/{s['id']}/send", headers=nurse)
    log = client.get("/api/audit?limit=20", headers=nurse).json()
    steps = {e["action"]: e for e in log if e["action"].startswith("doctor_summary")}
    for action in ("doctor_summary_prepared", "doctor_summary_reviewed", "doctor_summary_sent"):
        assert steps[action]["actor"] == "Nurse Sarah Johnson (RN)"
        assert steps[action]["at"]
    assert "No doctor was contacted" in steps["doctor_summary_sent"]["detail"]
    final = client.get(f"/api/doctor-summaries/{s['id']}/pdf", headers=nurse).content
    # brackets are escaped inside a PDF, so we look for the escaped form
    assert b"Prepared by Nurse Sarah Johnson \\(RN\\)" in final
    assert b"Reviewed by Nurse Sarah Johnson \\(RN\\)" in final
    assert b"simulated: no doctor was contacted" in final
    assert b"DRAFT" not in final


def test_approved_handover_is_labelled_as_ai_draft():
    nurse, carer1 = login("nurse1"), login("carer1")
    client.post("/api/carer/notes", json={"resident_id": 1, "text": "Coughing at lunch"}, headers=carer1)
    draft = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"]}, headers=carer1)
    s = prepare(nurse)
    assert "handover" not in [x["key"] for x in s["content"]["sections"]]  # not approved yet
    client.post(f"/api/handovers/{draft['id']}/review", json={"decision": "approve", "text": draft["text"]}, headers=nurse)
    s = prepare(nurse)
    h = section(s, "handover")
    assert h["label"].startswith("AI draft, checked and approved by Nurse Sarah Johnson")
    assert any("Coughing at lunch" in ln["text"] for ln in h["lines"])


def test_pdf_writer_handles_long_text_and_special_letters():
    blocks = [("title", "Whānau update (test)"), ("text", "Temperature 37.8 °C. " * 400)]
    data = make_pdf(blocks, footer="footer")
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert b"Whanau update \\(test\\)" in data        # macron replaced, brackets escaped
    assert b"/Count 2" in data or b"/Count 3" in data  # long text flows onto more pages


def test_doctor_page_opens_from_navbar_and_reports_links():
    # The navbar "Doctor PDF" and the Reports page button use /doctor-summary.
    for path in ("/doctor-summary", "/nurse/doctor-summary"):
        r = client.get(path)
        assert r.status_code == 200
        assert "Doctor summary" in r.text
