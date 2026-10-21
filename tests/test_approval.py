"""Nurse approval, carer view and audit log. No Ollama needed."""
import json

import pytest
from fastapi.testclient import TestClient

from app import guidance, ollama_client
from app.main import app

NURSE = {"X-Role": "nurse"}
CARER = {"X-Role": "carer"}


def line(text, source_id, quote):
    return {"text": text, "source_id": source_id, "quote": quote}


def source_id_for(resident_id, fragment):
    for source in guidance.build_sources(guidance.load_resident(resident_id)):
        if fragment in source.text:
            return source.id
    raise AssertionError(fragment)


@pytest.fixture
def client(monkeypatch):
    s_walk = source_id_for(2, "Keep the walking frame within reach")
    s_unsteady = source_id_for(2, "unsteady when standing")
    answer = {
        "watch_for": [line("Watch for unsteadiness when Ron stands up.", s_unsteady, "unsteady when standing")],
        "prevention": [line("Keep the walking frame within reach.", s_walk, "keep the walking frame within reach")],
    }
    monkeypatch.setattr(ollama_client, "chat_json", lambda *a, **k: json.dumps(answer))
    return TestClient(app)


def make_draft(client):
    response = client.post("/api/guidance/draft", json={"resident_id": 2})
    assert response.status_code == 200
    return response.json()["draft_id"]


def test_carers_see_nothing_until_a_nurse_approves(client):
    draft_id = make_draft(client)
    assert client.get("/api/guidance/2/approved").status_code == 404

    done = client.post(
        f"/api/guidance/draft/{draft_id}/decision",
        headers=NURSE,
        json={"decision": "approve", "reviewer": "Nurse Sam"},
    )
    assert done.status_code == 200 and done.json()["status"] == "approved"

    seen = client.get("/api/guidance/2/approved", headers=CARER).json()
    assert seen["approved_by"] == "Nurse Sam"
    assert [l["text"] for l in seen["prevention"]] == ["Keep the walking frame within reach."]


def test_only_a_nurse_can_review_or_approve(client):
    draft_id = make_draft(client)
    body = {"decision": "approve", "reviewer": "Casey Carer"}
    assert client.post(f"/api/guidance/draft/{draft_id}/decision", headers=CARER, json=body).status_code == 403
    assert client.post(f"/api/guidance/draft/{draft_id}/decision", json=body).status_code == 403
    assert client.get("/api/guidance/pending", headers=CARER).status_code == 403
    assert client.get("/api/audit", headers=CARER).status_code == 403
    assert client.get("/api/guidance/2/approved").status_code == 404  # still nothing approved


def test_nurse_can_edit_remove_and_add_lines(client):
    draft_id = make_draft(client)
    draft = client.get(f"/api/guidance/draft/{draft_id}", headers=NURSE).json()
    kept = draft["prevention"][0]
    response = client.post(
        f"/api/guidance/draft/{draft_id}/decision",
        headers=NURSE,
        json={
            "decision": "approve",
            "reviewer": "Nurse Sam",
            "watch_for": [{"text": "Watch for dizziness when Ron stands up.", "edited": True}],
            "prevention": [{"text": kept["text"], "source_id": kept["source_id"]}],
        },
    )
    assert response.status_code == 200
    final = response.json()
    assert final["watch_for"][0]["edited"] is True
    assert final["watch_for"][0]["source"] == "Written by the nurse"
    assert final["prevention"][0]["edited"] is False
    assert final["prevention"][0]["quote"]  # the AI's quote is kept for unchanged lines


def test_server_rejects_medicine_wording_and_fake_ai_lines(client):
    draft_id = make_draft(client)
    url = f"/api/guidance/draft/{draft_id}/decision"
    medicine = client.post(url, headers=NURSE, json={
        "decision": "approve", "reviewer": "Nurse Sam",
        "prevention": [{"text": "Give 500 mg of paracetamol.", "edited": True}]})
    assert medicine.status_code == 422 and "medicine" in medicine.json()["detail"]

    fake = client.post(url, headers=NURSE, json={
        "decision": "approve", "reviewer": "Nurse Sam",
        "prevention": [{"text": "The AI said this.", "source_id": "S1", "edited": False}]})
    assert fake.status_code == 422 and "does not match" in fake.json()["detail"]

    empty = client.post(url, headers=NURSE, json={
        "decision": "approve", "reviewer": "Nurse Sam", "watch_for": [], "prevention": []})
    assert empty.status_code == 422 and "nothing to approve" in empty.json()["detail"]


def test_reject_and_double_decision(client):
    draft_id = make_draft(client)
    url = f"/api/guidance/draft/{draft_id}/decision"
    rejected = client.post(url, headers=NURSE, json={"decision": "reject", "reviewer": "Nurse Sam", "note": "Too vague"})
    assert rejected.json()["status"] == "rejected"
    assert client.get("/api/guidance/2/approved").status_code == 404
    again = client.post(url, headers=NURSE, json={"decision": "approve", "reviewer": "Nurse Sam"})
    assert again.status_code == 409


def test_a_newer_approval_replaces_the_older_one(client):
    first, second = make_draft(client), make_draft(client)
    for draft_id in (first, second):
        client.post(f"/api/guidance/draft/{draft_id}/decision", headers=NURSE,
                    json={"decision": "approve", "reviewer": "Nurse Sam"})
    assert client.get("/api/guidance/2/approved").json()["draft_id"] == second
    assert client.get(f"/api/guidance/draft/{first}", headers=NURSE).json()["status"] == "replaced"


def test_pending_list_and_audit_log(client):
    draft_id = make_draft(client)
    pending = client.get("/api/guidance/pending", headers=NURSE).json()
    assert [p["draft_id"] for p in pending] == [draft_id] and pending[0]["resident"] == "Ron H."

    client.post(f"/api/guidance/draft/{draft_id}/decision", headers=NURSE,
                json={"decision": "approve", "reviewer": "Nurse Sam"})
    assert client.get("/api/guidance/pending", headers=NURSE).json() == []

    log = client.get("/api/audit", headers=NURSE).json()
    assert [(e["action"], e["role"]) for e in log] == [("approved", "nurse"), ("draft_created", "ai")]
    assert log[0]["actor"] == "Nurse Sam" and log[0]["draft_id"] == draft_id