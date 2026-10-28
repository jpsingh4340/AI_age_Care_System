"""Tests for the Care Priority Decision API (Tanveer).

They run WITHOUT Ollama: a fake model answers instead of the real AI.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import db, decision, ollama_client
from app.main import app
from app.routers import carer

client = TestClient(app)
NURSE = {"X-Role": "nurse"}
CARER = {"X-Role": "carer"}


def fake_chat_json(system, user, schema):
    """A pretend AI: finds a near fall or vomiting, and once makes up a quote."""
    concerns = []
    if "Nearly slipped" in user:
        concerns.append({"type": "Fall risk", "quote": "Nearly slipped when getting out of the chair",
                         "reason": "Lost balance while getting out of the chair.", "needs_check": True})
    if "Vomited" in user:
        concerns.append({"type": "Pain", "quote": "said her stomach really hurts",  # made up on purpose
                         "reason": "Pain should be checked.", "needs_check": True})
    if "refused dinner" in user:
        concerns.append({"type": "Not eating", "quote": "refused dinner",
                         "reason": "Did not eat dinner.", "needs_check": True})
    return json.dumps({"concerns": concerns})


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(carer, "DB_PATH", test_db)
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)
    decision._ai_memory.clear()


def test_ron_is_amber_because_of_a_carer_note():
    data = client.get("/api/residents/2/decision").json()
    assert data["rules"]["level"] == "Green"  # his vital signs are normal
    assert data["level"] == "Amber"  # but the carer note raises him
    ai_reason = [r for r in data["reasons"] if r["from"] == "ai"][0]
    assert ai_reason["quote"] == "Nearly slipped when getting out of the chair"
    assert ai_reason["source"] == "Carer note, 10:20"
    assert data["next_step"] == "A nurse should check the resident."


def test_rules_only_when_ai_is_off():
    data = client.get("/api/residents/2/decision?use_ai=false").json()
    assert data["level"] == "Green"
    assert data["ai"]["status"] == "off"


def test_made_up_quote_never_reaches_the_nurse():
    data = client.get("/api/residents/3/decision").json()
    assert data["ai"]["removed_by_check"] == 1
    assert all("stomach" not in r.get("quote", "") for r in data["reasons"])


def test_if_the_ai_fails_the_rules_still_work(monkeypatch):
    def broken(system, user, schema):
        raise ollama_client.OllamaError("Cannot reach Ollama.")
    monkeypatch.setattr(ollama_client, "chat_json", broken)
    data = client.get("/api/residents/1/decision").json()
    assert data["ai"]["status"] == "error"
    assert data["level"] == data["rules"]["level"]


def test_note_from_the_carer_page_is_read():
    r = client.post("/api/carer/concerns", json={
        "resident_id": "4", "type": "Not eating", "note": "Ahmed refused dinner tonight.", "carer": "Priya"})
    assert r.status_code == 201
    data = client.get("/api/residents/4/decision").json()
    assert data["level"] == "Amber"
    assert any(r.get("quote") == "refused dinner" for r in data["reasons"])


def test_unknown_resident_is_404():
    assert client.get("/api/residents/999/decision").status_code == 404


def test_a_carer_cannot_review():
    body = {"reviewer": "Priya", "suggested": "Amber", "final": "Amber"}
    assert client.post("/api/residents/2/decision/review", json=body, headers=CARER).status_code == 403


def test_nurse_accepts_and_it_is_in_the_audit_log():
    body = {"reviewer": "Nurse Sarah", "suggested": "Amber", "final": "Amber"}
    r = client.post("/api/residents/2/decision/review", json=body, headers=NURSE)
    assert r.status_code == 200
    assert r.json()["action"] == "priority_accepted"
    data = client.get("/api/residents/2/decision").json()
    assert data["last_review"]["actor"] == "Nurse Sarah"


def test_changing_the_priority_needs_a_reason():
    body = {"reviewer": "Nurse Sarah", "suggested": "Amber", "final": "Red"}
    r = client.post("/api/residents/2/decision/review", json=body, headers=NURSE)
    assert r.status_code == 422
    body["note"] = "Looked pale when I checked."
    r = client.post("/api/residents/2/decision/review", json=body, headers=NURSE)
    assert r.json()["action"] == "priority_changed"
    assert "from Amber to Red" in r.json()["detail"]


def test_the_nurse_choice_is_shown_after_a_change():
    body = {"reviewer": "Nurse Sarah", "suggested": "Amber", "final": "Red", "note": "Looked pale."}
    client.post("/api/residents/2/decision/review", json=body, headers=NURSE)
    review = client.get("/api/residents/2/decision").json()["last_review"]
    assert review["suggested"] == "Amber"
    assert review["final"] == "Red"