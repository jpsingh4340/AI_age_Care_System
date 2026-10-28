"""Tests for the AI layer of the Care Priority Decision feature (Tanveer).

These run WITHOUT Ollama: a fake model gives fixed answers, some of them wrong
on purpose, so we can test that MY checks catch the mistakes.
"""
import json

from app import decision_ai, ollama_client
from app.decision_rules import AMBER, GREEN, RED

NOTES = [
    {"time": "10:20", "text": "Nearly slipped when getting out of the chair."},
    {"time": "12:45", "text": "Only had a few sips of tea at lunch. No falls today."},
]


def use_fake_model(monkeypatch, concerns):
    """Make the AI return the given concerns, and count how often it is called."""
    calls = []

    def fake_chat_json(system, user, schema):
        calls.append(user)
        return json.dumps({"concerns": concerns})

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)
    return calls


def test_real_quote_is_kept_as_amber_with_its_source(monkeypatch):
    use_fake_model(monkeypatch, [{
        "type": "Fall risk", "quote": "Nearly slipped when getting out of the chair",
        "reason": "A near fall may mean a higher risk of falling.", "needs_check": True,
    }])
    kept, dropped = decision_ai.read_notes(NOTES)
    assert len(kept) == 1 and dropped == []
    assert kept[0]["level"] == AMBER
    assert kept[0]["source"] == "Carer note, 10:20"


def test_made_up_quote_is_removed(monkeypatch):
    use_fake_model(monkeypatch, [{
        "type": "Pain", "quote": "complained of strong chest pain",
        "reason": "Pain should be checked.", "needs_check": True,
    }])
    kept, dropped = decision_ai.read_notes(NOTES)
    assert kept == []
    assert dropped[0]["why"] == "The quote is not in any carer note."


def test_reason_with_a_medicine_is_removed(monkeypatch):
    use_fake_model(monkeypatch, [{
        "type": "Low fluids", "quote": "Only had a few sips of tea",
        "reason": "Give paracetamol and fluids.", "needs_check": True,
    }])
    kept, dropped = decision_ai.read_notes(NOTES)
    assert kept == []
    assert "medicine" in dropped[0]["why"]


def test_information_only_note_is_green(monkeypatch):
    use_fake_model(monkeypatch, [{
        "type": "Low fluids", "quote": "Only had a few sips of tea",
        "reason": "Drank a little at lunch.", "needs_check": False,
    }])
    kept, _ = decision_ai.read_notes(NOTES)
    assert kept[0]["level"] == GREEN


def test_ai_can_never_give_red(monkeypatch):
    use_fake_model(monkeypatch, [
        {"type": "Fall risk", "quote": "Nearly slipped", "reason": "Near fall.", "needs_check": True},
        {"type": "Low fluids", "quote": "a few sips of tea", "reason": "Drank little.", "needs_check": True},
    ])
    kept, _ = decision_ai.read_notes(NOTES)
    assert decision_ai.notes_level(kept) == AMBER
    assert all(concern["level"] != RED for concern in kept)


def test_no_notes_means_no_ai_call(monkeypatch):
    calls = use_fake_model(monkeypatch, [])
    assert decision_ai.read_notes([]) == ([], [])
    assert calls == []


def test_same_type_is_only_kept_once(monkeypatch):
    use_fake_model(monkeypatch, [
        {"type": "Fall risk", "quote": "Nearly slipped", "reason": "Near fall.", "needs_check": True},
        {"type": "Fall risk", "quote": "getting out of the chair", "reason": "Near fall.", "needs_check": True},
    ])
    kept, _ = decision_ai.read_notes(NOTES)
    assert len(kept) == 1
