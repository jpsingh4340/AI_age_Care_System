import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app
from app.routers import carer, patient

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_patient.db"
    monkeypatch.setattr(auth, "DB_PATH", test_db)
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(carer, "DB_PATH", test_db)
    monkeypatch.setattr(patient, "DB_PATH", test_db)
    auth.init_auth_db()


def test_patient_page_served():
    r = client.get("/patient")
    assert r.status_code == 200
    assert "Resident" in r.text or "Patient" in r.text


def test_get_patient_day():
    r = client.get("/api/patient/my-day?resident_id=1")
    assert r.status_code == 200
    data = r.json()
    assert data["resident_id"] == 1
    assert data["name"] == "Margaret T."
    assert "Room 101" in data["room"]
    assert len(data["schedule"]) > 0
    assert data["schedule"][0]["title"] == "Breakfast & Morning Refresh"


def test_carer_task_syncs_to_patient_schedule():
    # Carer logs task
    r_task = client.post("/api/carer/tasks", json={
        "resident_id": "1",
        "task": "Breakfast eaten",
        "status": "given",
        "carer": "Carer Priya"
    })
    assert r_task.status_code == 201

    # Patient views daily schedule
    day = client.get("/api/patient/my-day?resident_id=1").json()
    bf = next(item for item in day["schedule"] if "Breakfast" in item["title"])
    assert "Completed" in bf["status"]
    assert "Priya" in bf["completed_by"]


def test_patient_wellbeing_checkin():
    # Good sentiment
    ok = client.post("/api/patient/wellbeing?resident_id=1", json={
        "sentiment": "great",
        "note": "Feeling rested"
    })
    assert ok.status_code == 200
    assert ok.json()["alert_triggered"] is False

    # Discomfort/pain triggers alarm in carer concerns
    pain = client.post("/api/patient/wellbeing?resident_id=1", json={
        "sentiment": "in_pain",
        "note": "Right knee feels stiff and painful"
    })
    assert pain.status_code == 200
    assert pain.json()["alert_triggered"] is True

    # Verify alert appears in carer today
    today = client.get("/api/carer/today?resident_id=1").json()
    assert any("pain" in c["note"].lower() for c in today["concerns"])


def test_patient_call_bell():
    bell = client.post("/api/patient/call-bell?resident_id=1", json={
        "request_type": "Need assistance getting to the chair"
    })
    assert bell.status_code == 200
    assert bell.json()["status"] == "sent"

    # Verify concern raised on carer feed
    today = client.get("/api/carer/today?resident_id=1").json()
    assert any("CALL BELL" in c["note"] for c in today["concerns"])


def test_patient_companion_orientation_question():
    resp = client.post("/api/patient/companion?resident_id=1", json={
        "question": "What is for lunch today?"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data and len(data["reply"]) > 5
    assert "speech_text" in data
    assert data["emergency_alert"] is False
    assert len(data["suggested_followups"]) > 0


def test_patient_companion_emergency_safety_escalation():
    resp = client.post("/api/patient/companion?resident_id=1", json={
        "question": "Help, I fell on the floor and my hip hurts bad"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["emergency_alert"] is True
    assert "still" in data["reply"].lower() or "alerted" in data["reply"].lower()

    # Verify that the emergency automatically raised an alarm on the carer feed
    today = client.get("/api/carer/today?resident_id=1").json()
    assert any("Emergency" in c["note"] or "AI Voice Companion" in c["note"] for c in today["concerns"])


def test_patient_detailed_day_profile():
    day = client.get("/api/patient/my-day?resident_id=1").json()
    assert day["profile_details"] is not None
    assert day["profile_details"]["preferred_name"] == "Peggy"
    assert day["profile_details"]["age"] == 82
    assert "Claire" in day["profile_details"]["emergency_contact"]["name"]
    assert len(day["meals_today"]) >= 3
    assert len(day["activities_today"]) >= 2
    assert len(day["family_messages"]) >= 1


def test_patient_log_water_and_family_reply():
    # Resident logs 1 glass of water
    w_res = client.post("/api/patient/log-water?resident_id=1", json={"amount_cups": 1})
    assert w_res.status_code == 200

    # Verify water count shows in day response
    day = client.get("/api/patient/my-day?resident_id=1").json()
    assert day["water_cups_logged"] >= 1

    # Verify carer feed sees the drink logged
    carer_today = client.get("/api/carer/today?resident_id=1").json()
    assert any(t["task"] == "Offer a drink" for t in carer_today["tasks"])

    # Family reply
    fam_res = client.post("/api/patient/family-reply?resident_id=1")
    assert fam_res.status_code == 200
    assert fam_res.json()["ok"] is True
