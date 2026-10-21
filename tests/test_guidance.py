"""Feature A tests. They run WITHOUT Ollama, using a fake model that makes mistakes on purpose."""
import json

import pytest
from fastapi.testclient import TestClient

from app import guidance, ollama_client
from app.main import app
from app.schemas import GuidanceLine


def good(text, source_id, quote):
    return {"text": text, "source_id": source_id, "quote": quote}


def make_fake_model(watch_for, prevention):
    def fake_chat_json(system, user, schema):
        return json.dumps({"watch_for": watch_for, "prevention": prevention})

    return fake_chat_json


def source_id_for(resident_id, fragment):
    resident = guidance.load_resident(resident_id)
    for source in guidance.build_sources(resident):
        if fragment in source.text:
            return source.id
    raise AssertionError(f"no source contains {fragment!r}")


def test_sources_are_this_residents_plan_plus_matching_reference_notes():
    sources = guidance.build_sources(guidance.load_resident(2))  # Ron: falls + hydration
    labels = {s.source for s in sources}
    assert "Care plan for Ron H." in labels
    assert "Reference note: Falls" in labels
    assert "Reference note: Hydration" in labels
    assert "Reference note: Skin and pressure areas" not in labels  # not Ron's condition
    assert not any("Margaret" in label for label in labels)  # no one else's plan
    assert [s.id for s in sources][:2] == ["S1", "S2"]


def test_good_line_passes_every_check():
    sources = guidance.build_sources(guidance.load_resident(2))
    by_id = {s.id: s for s in sources}
    sid = source_id_for(2, "Keep the walking frame within reach, keep floors clear")
    line = GuidanceLine(
        text="Keep the walking frame within reach and the floor clear.",
        source_id=sid,
        quote="keep the walking frame within reach",
    )
    assert guidance.check_line(line, by_id) is None


@pytest.mark.parametrize(
    "line, expected",
    [
        (GuidanceLine(text="Offer a drink often.", source_id="S99", quote="offer a drink often"),
         "does not exist"),
        (GuidanceLine(text="Offer a drink often.", source_id="S1", quote="words that are not there"),
         "not in the cited source"),
    ],
)
def test_bad_source_or_quote_is_rejected(line, expected):
    by_id = {s.id: s for s in guidance.build_sources(guidance.load_resident(1))}
    assert expected in guidance.check_line(line, by_id)


def test_medicine_dose_and_diagnosis_are_blocked():
    sid = source_id_for(1, "Offer a drink at least every 2 hours")
    by_id = {s.id: s for s in guidance.build_sources(guidance.load_resident(1))}
    quote = "Offer a drink at least every 2 hours"
    for text in [
        "Offer a drink and give 500 mg of paracetamol.",
        "Offer a drink every 2 hours to treat the diagnosis.",
        "Offer a drink and ask the doctor to prescribe something.",
    ]:
        reason = guidance.check_line(GuidanceLine(text=text, source_id=sid, quote=quote), by_id)
        assert reason and "medicine" in reason


def test_line_with_a_real_quote_but_invented_content_is_rejected():
    sid = source_id_for(1, "Offer a drink at least every 2 hours")
    by_id = {s.id: s for s in guidance.build_sources(guidance.load_resident(1))}
    line = GuidanceLine(
        text="Check blood pressure daily and book a scan every month.",
        source_id=sid,
        quote="Offer a drink at least every 2 hours",
    )
    assert "not in the cited source" in guidance.check_line(line, by_id)


def test_draft_keeps_good_lines_and_records_removed_ones(monkeypatch):
    sid = source_id_for(2, "Keep the walking frame within reach, keep floors clear")
    watch_for = [
        good("Watch for unsteadiness when Ron stands up.", source_id_for(2, "unsteady when standing"),
             "unsteady when standing"),
        good("Ron may be fine without any checks.", "S99", "made up"),  # bad source
    ]
    prevention = [
        good("Keep the walking frame within reach.", sid, "keep the walking frame within reach"),
        good("Keep the walking frame within reach.", sid, "keep the walking frame within reach"),  # duplicate
    ]
    monkeypatch.setattr(ollama_client, "chat_json", make_fake_model(watch_for, prevention))

    resident, sources, kept_watch, kept_prev, dropped = guidance.draft_guidance(2)

    assert resident["name"] == "Ron H."
    assert [line.text for line in kept_watch] == ["Watch for unsteadiness when Ron stands up."]
    assert [line.text for line in kept_prev] == ["Keep the walking frame within reach."]
    assert {d.reason for d in dropped} == {"The source number does not exist.", "Duplicate line."}
    assert kept_prev[0].source == "Reference note: Falls"


def test_unknown_resident_returns_none():
    assert guidance.draft_guidance(999) is None


def test_api_returns_a_draft_for_the_nurse(monkeypatch):
    sid = source_id_for(3, "Record any vomiting")
    monkeypatch.setattr(
        ollama_client,
        "chat_json",
        make_fake_model(
            [],
            [good("Record the time and amount of any vomiting.", sid, "Record any vomiting")],
        ),
    )
    client = TestClient(app)
    response = client.post("/api/guidance/draft", json={"resident_id": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["resident"] == "Joan P."
    assert body["status"] == "draft"
    assert "nurse must approve" in body["status_note"]
    assert len(body["prevention"]) == 1
    assert body["prevention"][0]["source"] == "Care plan for Joan P."


def test_api_404_and_503(monkeypatch):
    client = TestClient(app)
    assert client.post("/api/guidance/draft", json={"resident_id": 999}).status_code == 404

    def broken(*args, **kwargs):
        raise ollama_client.OllamaError("Cannot reach Ollama.")

    monkeypatch.setattr(ollama_client, "chat_json", broken)
    response = client.post("/api/guidance/draft", json={"resident_id": 1})
    assert response.status_code == 503


def test_screen_and_resident_list_are_served():
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "Draft guidance" in page.text
    people = client.get("/api/residents").json()
    assert [p["name"] for p in people] == ["Margaret T.", "Ron H.", "Joan P.", "Ahmed K."]
    assert "Falls risk" in people[1]["conditions"]