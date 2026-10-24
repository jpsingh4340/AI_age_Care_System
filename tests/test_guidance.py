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

    resident, sources, kept_watch, kept_prev, dropped, gaps = guidance.draft_guidance(2)

    assert resident["name"] == "Ron H."
    assert [line.text for line in kept_watch] == ["Watch for unsteadiness when Ron stands up."]
    assert [line.text for line in kept_prev] == ["Keep the walking frame within reach."]
    assert {d.reason for d in dropped} == {"The source number does not exist.", "Duplicate line."}
    assert kept_prev[0].source == "Reference note: Falls"
    assert gaps == ["Hydration (symptoms to watch for)", "Hydration (prevention steps)"]  # the nurse is told


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

    



# ---------- coverage: every recorded condition should get at least one line ----------
def lines_from(resident_id, topic, count=1):
    """Good lines that quote a whole reference-note sentence for this topic."""
    sources = [s for s in guidance.build_sources(guidance.load_resident(resident_id)) if s.topic == topic]
    return [good(s.text, s.id, s.text) for s in sources[:count]]


def recording_model(answers):
    """A fake model that returns the next prepared answer each time and remembers what it was asked."""
    asked = []

    def fake_chat_json(system, user, schema):
        asked.append((user, schema))
        return json.dumps(answers[min(len(asked), len(answers)) - 1])

    return fake_chat_json, asked


def test_a_missing_condition_gets_one_extra_try_using_only_its_sources(monkeypatch):
    first = {"watch_for": lines_from(2, "falls"), "prevention": lines_from(2, "falls", 2)[1:]}
    second = {"watch_for": lines_from(2, "hydration"), "prevention": lines_from(2, "hydration", 2)[1:]}
    model, asked = recording_model([first, second])
    monkeypatch.setattr(ollama_client, "chat_json", model)

    _, sources, watch, prevention, dropped, gaps = guidance.draft_guidance(2)

    assert len(asked) == 2
    assert "Reference note: Hydration" in asked[1][0] and "Reference note: Falls" not in asked[1][0]
    assert asked[1][1]["properties"]["watch_for"]["minItems"] == 1
    topics = {s.id: s.topic for s in sources}
    assert {topics[line.source_id] for line in watch + prevention} == {"falls", "hydration"}
    assert gaps == []


def test_no_extra_try_when_every_condition_is_covered(monkeypatch):
    answer = {
        "watch_for": lines_from(2, "falls") + lines_from(2, "hydration"),
        "prevention": lines_from(2, "falls", 2)[1:] + lines_from(2, "hydration", 2)[1:],
    }
    model, asked = recording_model([answer])
    monkeypatch.setattr(ollama_client, "chat_json", model)

    *_, gaps = guidance.draft_guidance(2)

    assert len(asked) == 1
    assert gaps == []


def test_a_gap_is_reported_when_the_extra_try_also_fails(monkeypatch):
    first = {"watch_for": lines_from(2, "falls"), "prevention": lines_from(2, "falls", 2)[1:]}
    nothing_useful = {"watch_for": [good("Made up.", "S99", "made up")], "prevention": []}
    model, asked = recording_model([first, nothing_useful])
    monkeypatch.setattr(ollama_client, "chat_json", model)

    _, _, watch, prevention, dropped, gaps = guidance.draft_guidance(2)

    assert gaps == ["Hydration (symptoms to watch for)", "Hydration (prevention steps)"]
    assert watch and prevention  # the falls lines are still kept
    assert any(d.reason == "The source number does not exist." for d in dropped)


def test_a_broken_extra_try_does_not_lose_the_first_answer(monkeypatch):
    first = {"watch_for": lines_from(2, "falls"), "prevention": lines_from(2, "falls", 2)[1:]}
    calls = []

    def flaky(system, user, schema):
        calls.append(1)
        if len(calls) == 2:
            raise ollama_client.OllamaError("token repeat limit reached")
        return json.dumps(first)

    monkeypatch.setattr(ollama_client, "chat_json", flaky)

    _, _, watch, prevention, _, gaps = guidance.draft_guidance(2)

    assert len(calls) == 2 and watch and prevention
    assert gaps == ["Hydration (symptoms to watch for)", "Hydration (prevention steps)"]

def test_api_tells_the_nurse_about_gaps(monkeypatch):
    first = {"watch_for": lines_from(2, "falls"), "prevention": lines_from(2, "falls", 2)[1:]}
    model, _ = recording_model([first, {"watch_for": [], "prevention": []}])
    monkeypatch.setattr(ollama_client, "chat_json", model)
    client = TestClient(app)

    body = client.post("/api/guidance/draft", json={"resident_id": 2}).json()
    assert body["gaps"] == ["Hydration (symptoms to watch for)", "Hydration (prevention steps)"]

    saved = client.get(f"/api/guidance/draft/{body['draft_id']}", headers={"X-Role": "nurse"}).json()
    assert saved["gaps"] == body["gaps"]



def test_a_condition_with_only_a_watch_line_still_needs_a_prevention_line(monkeypatch):
    # Ron's falls: the model wrote a "watch for" line but no prevention line. This was the real problem.
    only_watch = {
        "watch_for": lines_from(2, "falls") + lines_from(2, "hydration"),
        "prevention": lines_from(2, "hydration", 2)[1:],
    }
    falls_prevention = {"watch_for": [], "prevention": lines_from(2, "falls", 2)[1:]}
    model, asked = recording_model([only_watch, falls_prevention])
    monkeypatch.setattr(ollama_client, "chat_json", model)

    _, _, watch, prevention, _, gaps = guidance.draft_guidance(2)

    assert len(asked) == 2
    assert "Falls (prevention steps)" in asked[1][0]
    assert any("walking frame" in line.text for line in prevention)
    assert gaps == []


def test_lines_that_say_almost_the_same_thing_are_removed(monkeypatch):
    sid = source_id_for(4, "dry mouth, dark urine")
    quote = "dry mouth, dark urine"
    same_idea = [
        good("A dry mouth, dark urine, or refusal to drink.", sid, quote),
        good("Refusal to drink or dark urine.", sid, quote),
        good("Dark urine or refusal to drink.", sid, quote),
    ]
    drink_prevention = lines_from(4, "hydration", 2)[1:]
    model, _ = recording_model([{"watch_for": same_idea, "prevention": drink_prevention}])
    monkeypatch.setattr(ollama_client, "chat_json", model)

    _, _, watch, _, dropped, _ = guidance.draft_guidance(4)

    assert [line.text for line in watch] == ["A dry mouth, dark urine, or refusal to drink."]
    assert [d.reason for d in dropped].count("Almost the same as another line.") == 2