from fastapi.testclient import TestClient

from app.main import app
from app.routers import ask

client = TestClient(app)


def fake_models(names):
    async def _f():
        return names
    return _f


def test_models_lists_chat_models(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models(["qwen2.5:3b"]))
    r = client.get("/api/ask/models")
    assert r.status_code == 200
    assert r.json()["models"] == ["qwen2.5:3b"]
    assert r.json()["ollama_running"] is True


def test_ask_returns_answer(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models(["qwen2.5:3b"]))

    async def fake_chat(model, messages):
        return "Check the brakes on the chair."
    monkeypatch.setattr(ask, "ask_ollama", fake_chat)
    r = client.post("/api/ask", json={"question": "how to transfer?", "model": "qwen2.5:3b"})
    assert r.status_code == 200
    assert r.json()["answer"] == "Check the brakes on the chair."
    assert r.json()["grounded"] is False


def test_ask_uses_guidance_when_found(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models(["qwen2.5:3b"]))
    async def fake_context(request, resident_id, role):
        return "Lock wheels first.", ["Transfers v1"]
    monkeypatch.setattr(ask, "get_context", fake_context)
    seen = {}

    async def fake_chat(model, messages):
        seen["system"] = messages[0]["content"]
        return "Lock the wheels first."
    monkeypatch.setattr(ask, "ask_ollama", fake_chat)
    r = client.post("/api/ask", json={"question": "how to transfer?", "resident_id": 1})
    assert r.json()["grounded"] is True
    assert r.json()["sources"] == ["Transfers v1"]
    assert "Lock wheels first." in seen["system"]


def test_ask_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models(["qwen2.5:3b"]))
    r = client.post("/api/ask", json={"question": "hello there", "model": "llama3:70b"})
    assert r.status_code == 400


def test_ask_when_ollama_down(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models([]))
    r = client.post("/api/ask", json={"question": "hello there"})
    assert r.status_code == 503


def test_embed_models_hidden():
    names = ["nomic-embed-text:latest", "qwen2.5:3b"]
    assert [n for n in names if not n.startswith(ask.EMBED_ONLY)] == ["qwen2.5:3b"]


def test_no_resident_means_general_answer(monkeypatch):
    monkeypatch.setattr(ask, "installed_chat_models", fake_models(["qwen2.5:3b"]))

    async def fake_chat(model, messages):
        return "ok"
    monkeypatch.setattr(ask, "ask_ollama", fake_chat)
    r = client.post("/api/ask", json={"question": "hello there"})
    assert r.json()["grounded"] is False