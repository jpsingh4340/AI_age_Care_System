"""Tests that run WITHOUT Ollama, using a fake model.

They test OUR code: the evidence check, the RAG search and the API.
They do not test how smart the real small model is. That needs the
labelled test notes in Studio 5 week 5 and 6.
"""
import json
import re
import zlib

import pytest
from fastapi.testclient import TestClient

from app import ollama_client, rag, slm
from app.main import app

NOTE = "Margaret refused lunch again today and only had a few sips of tea. No falls today."


def fake_embed(texts):
    """A pretend embedding: counts words. Similar words give similar numbers."""
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for word in re.findall(r"[a-z]+", text.lower()):
            vector[zlib.crc32(word.encode()) % 64] += 1
        vectors.append(vector)
    return vectors


def fake_chat_json(system, user, schema):
    """A pretend small model that makes some mistakes on purpose."""
    if "numbered care plan lines" in system:
        return json.dumps(
            {
                "checks": [
                    {"item_number": 1, "status": "off_plan", "note_evidence": "a few sips of tea"},
                    {"item_number": 2, "status": "met", "note_evidence": "words not in the note"},
                    {"item_number": 99, "status": "met", "note_evidence": "x"},
                ]
            }
        )
    return json.dumps(
        {
            "summary": "Margaret ate and drank very little today.",
            "flags": [
                {"type": "Not eating", "evidence": "refused lunch again"},
                {"type": "Low fluids", "evidence": "only had a few sips of tea"},
                {"type": "Fall risk", "evidence": "fell in the hallway"},  # made up
            ],
        }
    )


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch):
    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)
    monkeypatch.setattr(ollama_client, "embed", fake_embed)
    monkeypatch.setattr(rag, "_index", None)  # rebuild the index for each test


def test_evidence_check_ignores_case_and_spacing():
    assert slm.evidence_in_note("Refused  LUNCH again", NOTE)
    assert not slm.evidence_in_note("fell in the hallway", NOTE)
    assert not slm.evidence_in_note("", NOTE)


def test_made_up_flag_is_dropped():
    analysis, dropped = slm.analyse_note(NOTE)
    assert [flag.type for flag in analysis.flags] == ["Not eating", "Low fluids"]
    assert [flag.type for flag in dropped] == ["Fall risk"]


def test_retrieval_only_uses_this_residents_plan():
    results = rag.retrieve(1, NOTE)
    texts = [item["text"] for item in results]
    assert any("Offer a drink at least every 2 hours" in text for text in texts)
    assert not any("Ron" in item["source"] for item in results)  # no one else's plan
    assert len(results) == 5


def test_plan_check_needs_proof_and_ignores_bad_numbers():
    checks, _ = rag.check_plan(1, NOTE)
    assert sorted(check.status for check in checks) == ["off_plan", "unclear"]  # 99 ignored


def test_api_returns_a_draft_for_the_nurse():
    client = TestClient(app)
    response = client.post("/api/analyse", json={"resident_id": 1, "note": NOTE})
    assert response.status_code == 200
    body = response.json()
    assert len(body["flags"]) == 2
    assert len(body["dropped_flags"]) == 1
    assert "nurse must check" in body["status_note"]


def test_api_can_skip_rag():
    client = TestClient(app)
    response = client.post(
        "/api/analyse", json={"resident_id": 1, "note": NOTE, "use_rag": False}
    )
    assert response.status_code == 200
    assert response.json()["plan_checks"] == []


def test_api_gives_a_clear_error_when_ollama_is_down(monkeypatch):
    def broken(*args, **kwargs):
        raise ollama_client.OllamaError("Cannot reach Ollama.")

    monkeypatch.setattr(ollama_client, "chat_json", broken)
    response = TestClient(app).post("/api/analyse", json={"resident_id": 1, "note": NOTE})
    assert response.status_code == 503
    assert "Cannot reach Ollama" in response.json()["detail"]
