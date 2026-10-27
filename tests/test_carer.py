import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import carer

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    # use a throwaway db so tests never touch data/agecare.db
    monkeypatch.setattr(carer, "DB_PATH", tmp_path / "test.db")


def test_save_task_shows_today():
    r = client.post("/api/carer/tasks", json={"resident_id": "1", "task": "Offer a drink", "status": "given", "carer": "Priya"})
    assert r.status_code == 201
    today = client.get("/api/carer/today?resident_id=1").json()
    assert today["tasks"][0]["task"] == "Offer a drink"
    assert today["tasks"][0]["carer"] == "Priya"


def test_bad_status_rejected():
    r = client.post("/api/carer/tasks", json={"resident_id": "1", "task": "Offer a drink", "status": "maybe", "carer": "Priya"})
    assert r.status_code == 422


def test_vitals_normal():
    r = client.post("/api/carer/vitals", json={"resident_id": "1", "pulse": 72, "temperature": 36.8, "carer": "Priya"})
    assert r.status_code == 201
    assert r.json()["tell_nurse"] is False


def test_vitals_outside_range_tells_nurse():
    r = client.post("/api/carer/vitals", json={"resident_id": "1", "spo2": 90, "carer": "Priya"})
    assert r.json()["tell_nurse"] is True


def test_vitals_impossible_number_rejected():
    r = client.post("/api/carer/vitals", json={"resident_id": "1", "pulse": 500, "carer": "Priya"})
    assert r.status_code == 422


def test_vitals_empty_rejected():
    r = client.post("/api/carer/vitals", json={"resident_id": "1", "carer": "Priya"})
    assert r.status_code == 400


def test_concern_saved_and_type_checked():
    ok = client.post("/api/carer/concerns", json={"resident_id": "2", "type": "Not drinking", "note": "Only a few sips at lunch", "carer": "Priya"})
    assert ok.status_code == 201
    bad = client.post("/api/carer/concerns", json={"resident_id": "2", "type": "Something else", "note": "test note", "carer": "Priya"})
    assert bad.status_code == 400
    today = client.get("/api/carer/today").json()
    assert len(today["concerns"]) == 1


def test_today_only_shows_that_resident():
    client.post("/api/carer/tasks", json={"resident_id": "1", "task": "Lunch eaten", "status": "refused", "carer": "Priya"})
    client.post("/api/carer/tasks", json={"resident_id": "2", "task": "Lunch eaten", "status": "given", "carer": "Priya"})
    assert len(client.get("/api/carer/today?resident_id=1").json()["tasks"]) == 1