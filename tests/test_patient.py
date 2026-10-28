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
