"""The model call tries again once if Ollama stops a repeating answer. No Ollama needed."""
import pytest

from app import guidance, ollama_client


def test_retries_once_when_the_model_repeats_itself(monkeypatch):
    calls = []

    def fake_post(path, payload, timeout=180):
        calls.append(payload["options"])
        if len(calls) == 1:
            raise ollama_client.OllamaError(
                "Ollama returned an error (500): prediction aborted, token repeat limit reached."
            )
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(ollama_client, "_post", fake_post)
    assert ollama_client.chat_json("system", "user", {}) == "{}"
    assert len(calls) == 2
    assert calls[0]["temperature"] == 0
    assert calls[1]["temperature"] == 0.3 and calls[1]["repeat_penalty"] == 1.15


def test_other_errors_are_not_retried(monkeypatch):
    calls = []

    def fake_post(path, payload, timeout=180):
        calls.append(1)
        raise ollama_client.OllamaError("Cannot reach Ollama.")

    monkeypatch.setattr(ollama_client, "_post", fake_post)
    with pytest.raises(ollama_client.OllamaError):
        ollama_client.chat_json("system", "user", {})
    assert len(calls) == 1


def test_schema_sent_to_the_model_has_size_limits():
    schema = guidance._limited_schema()
    assert schema["properties"]["watch_for"]["maxItems"] == 4
    assert schema["$defs"]["GuidanceLine"]["properties"]["text"]["maxLength"] == 220