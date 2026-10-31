"""Carer to nurse handover, daily care schedule, and nurse/family messages."""
import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app
from app.routers import carer, handover

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(carer, "DB_PATH", test_db)
    monkeypatch.setattr(auth, "DB_PATH", test_db)
    auth.init_auth_db()
    # never wait on Ollama in tests: the rule-based drafts are used instead
    def no_model(system, user):
        raise RuntimeError("model off")
    monkeypatch.setattr(handover, "ask_model", no_model)


def login(username):
    token = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_quick_notes_need_sign_in_and_show_today():
    assert client.post("/api/carer/notes", json={"resident_id": 1, "text": "Slept well"}).status_code == 401
    carer1 = login("carer1")
    r = client.post("/api/carer/notes", json={"resident_id": 1, "text": "Slept well after lunch"}, headers=carer1)
    assert r.status_code == 201
    notes = client.get("/api/carer/notes?resident_id=1", headers=carer1).json()
    assert notes[0]["text"] == "Slept well after lunch"
    assert notes[0]["carer"] == "Carer Priya Patel"
    # a carer can remove their own note, but a nurse cannot remove it for them
    assert client.delete(f"/api/carer/notes/{notes[0]['id']}", headers=login("nurse1")).status_code == 403
    assert client.delete(f"/api/carer/notes/{notes[0]['id']}", headers=carer1).status_code == 200


def test_nurse_builds_schedule_and_carer_ticks_it_off():
    nurse, carer1 = login("nurse1"), login("carer1")
    assert client.post("/api/schedule", json={"resident_id": 1, "task": "Shower"}, headers=carer1).status_code == 403

    shower = client.post("/api/schedule", json={"resident_id": 1, "task": "Shower", "time": "08:00"}, headers=nurse).json()
    walk = client.post("/api/schedule", json={"resident_id": 1, "task": "Walk", "time": "07:30"}, headers=nurse).json()
    items = client.get("/api/schedule?resident_id=1", headers=carer1).json()
    assert [i["task"] for i in items] == ["Walk", "Shower"]  # sorted by time

    edited = client.put(f"/api/schedule/{walk['id']}", json={"task": "Walk with frame", "time": "10:00"}, headers=nurse)
    assert edited.json()["task"] == "Walk with frame"

    ticked = client.post(f"/api/schedule/{shower['id']}/done", json={"done": True}, headers=carer1).json()
    assert ticked["done_by"] == "Carer Priya Patel"
    unticked = client.post(f"/api/schedule/{shower['id']}/done", json={"done": False}, headers=carer1).json()
    assert unticked["done_by"] is None

    assert client.delete(f"/api/schedule/{walk['id']}", headers=nurse).status_code == 200
    assert [i["task"] for i in client.get("/api/schedule?resident_id=1", headers=nurse).json()] == ["Shower"]


def test_bad_schedule_time_rejected():
    r = client.post("/api/schedule", json={"resident_id": 1, "task": "Shower", "time": "8am"}, headers=login("nurse1"))
    assert r.status_code == 422


def test_handover_from_carer_to_nurse_to_family():
    nurse, carer1, family = login("nurse1"), login("carer1"), login("family1")
    client.post("/api/carer/notes", json={"resident_id": 1, "text": "Coughing at lunch"}, headers=carer1)
    client.post("/api/carer/tasks", json={"resident_id": "1", "task": "Lunch eaten", "status": "refused", "carer": "Priya"}, headers=carer1)
    item = client.post("/api/schedule", json={"resident_id": 1, "task": "Shower", "time": "08:00"}, headers=nurse).json()

    draft = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    assert draft["status"] == "draft"
    assert draft["drafted_by"] == "Rules"
    kinds = [e["kind"] for e in draft["sources"]["entries"]]
    assert "Note" in kinds and "Task" in kinds
    assert "08:00 Shower" in draft["sources"]["not_done"]
    assert "Coughing at lunch" in draft["text"]

    # the nurse does not see a draft until the carer sends it
    assert client.get("/api/handovers?status=draft", headers=nurse).json() == []
    assert client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"]}, headers=nurse).status_code == 403
    sent = client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"] + " Family visiting at 4."}, headers=carer1)
    assert sent.json()["status"] == "waiting"
    assert [h["id"] for h in client.get("/api/handovers?status=waiting", headers=nurse).json()] == [draft["id"]]

    # carers cannot approve, and a family update needs an approved handover
    review = {"decision": "approve", "text": "Coughing at lunch, refused lunch. Nurse checked."}
    assert client.post(f"/api/handovers/{draft['id']}/review", json=review, headers=carer1).status_code == 403
    assert client.post(f"/api/handovers/{draft['id']}/family-draft", headers=nurse).status_code == 409

    approved = client.post(f"/api/handovers/{draft['id']}/review", json=review, headers=nurse).json()
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "Nurse Sarah Johnson (RN)"
    assert client.post(f"/api/handovers/{draft['id']}/review", json=review, headers=nurse).status_code == 409

    fam = client.post(f"/api/handovers/{draft['id']}/family-draft", headers=nurse).json()
    assert fam["status"] == "draft" and fam["text"].startswith("Kia ora")
    assert client.get("/api/family/me", headers=family).json()["updates"] == []
    client.post(f"/api/family-updates/{fam['id']}/send", json={"text": "Kia ora, Margaret had a quiet day."}, headers=nurse)
    assert client.get("/api/family/me", headers=family).json()["updates"][0]["text"] == "Kia ora, Margaret had a quiet day."

    # the next handover only covers what happened after this one was sent
    nxt = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    assert all(e["text"] != "Coughing at lunch" for e in nxt["sources"]["entries"])


def test_nurse_sends_handover_back_with_a_reason():
    nurse, carer1 = login("nurse1"), login("carer1")
    client.post("/api/carer/notes", json={"resident_id": 2, "text": "Walked to the lounge"}, headers=carer1)
    draft = client.post("/api/handovers/draft", json={"resident_id": 2}, headers=carer1).json()
    client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"]}, headers=carer1)

    no_reason = {"decision": "return", "text": draft["text"], "note": ""}
    assert client.post(f"/api/handovers/{draft['id']}/review", json=no_reason, headers=nurse).status_code == 422
    back = client.post(f"/api/handovers/{draft['id']}/review", json={**no_reason, "note": "Add how far he walked."}, headers=nurse).json()
    assert back["status"] == "returned" and back["review_note"] == "Add how far he walked."

    again = client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"] + " About 50 metres."}, headers=carer1).json()
    assert again["status"] == "waiting" and again["review_note"] == ""


def test_ai_draft_with_new_medicine_words_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(handover, "ask_model", lambda s, u: "Margaret coughed at lunch. Give her 500 mg paracetamol.")
    carer1 = login("carer1")
    client.post("/api/carer/notes", json={"resident_id": 1, "text": "Coughing at lunch"}, headers=carer1)
    draft = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    assert draft["drafted_by"] == "Rules"
    assert "paracetamol" not in draft["text"]


def test_ai_draft_is_used_when_safe(monkeypatch):
    monkeypatch.setattr(handover, "ask_model", lambda s, u: "Margaret coughed at lunch and did not finish her meal.")
    carer1 = login("carer1")
    client.post("/api/carer/notes", json={"resident_id": 1, "text": "Coughing at lunch"}, headers=carer1)
    draft = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    assert draft["drafted_by"] == "AI"


def test_nurse_and_family_chat_about_one_resident():
    nurse, family = login("nurse1"), login("family1")  # family1 is linked to resident 1
    assert client.post("/api/chat/1", json={"text": "Can I visit Saturday?"}, headers=family).status_code == 201
    assert client.post("/api/chat/2", json={"text": "Hello"}, headers=family).status_code == 403
    assert client.get("/api/chat/2", headers=family).status_code == 403
    assert client.get("/api/chat/1", headers=login("carer1")).status_code == 403

    client.post("/api/chat/1", json={"text": "Yes, see you then."}, headers=nurse)
    thread = client.get("/api/chat/1", headers=family).json()
    assert [(m["sender_role"], m["text"]) for m in thread] == [("family", "Can I visit Saturday?"), ("nurse", "Yes, see you then.")]

    # messages sent from the older family endpoint join the same thread
    client.post("/api/family/messages", json={"text": "Thank you"}, headers=family)
    assert client.get("/api/chat/1", headers=nurse).json()[-1]["text"] == "Thank you"

    assert client.post("/api/chat/1/read", headers=nurse).json()["marked"] == 2
    assert all(m["read_by"] for m in client.get("/api/chat/1", headers=nurse).json())


def test_family_draft_with_clinical_readings_falls_back_to_rules(monkeypatch):
    nurse, carer1 = login("nurse1"), login("carer1")
    client.post("/api/carer/notes", json={"resident_id": 1, "text": "Coughing at lunch"}, headers=carer1)
    draft = client.post("/api/handovers/draft", json={"resident_id": 1}, headers=carer1).json()
    client.post(f"/api/handovers/{draft['id']}/send", json={"text": draft["text"]}, headers=carer1)
    client.post(f"/api/handovers/{draft['id']}/review", json={"decision": "approve", "text": draft["text"]}, headers=nurse)

    monkeypatch.setattr(handover, "ask_model", lambda s, u: "Kia ora. Margaret has a low SpO2 today.")
    fam = client.post(f"/api/handovers/{draft['id']}/family-draft", headers=nurse).json()
    assert fam["drafted_by"] == "Rules"
    assert "SpO2" not in fam["text"]

    monkeypatch.setattr(handover, "ask_model", lambda s, u: "Kia ora. Margaret had a quiet day and enjoyed her shower.")
    fam = client.post(f"/api/handovers/{draft['id']}/family-draft", headers=nurse).json()
    assert fam["drafted_by"] == "AI"
