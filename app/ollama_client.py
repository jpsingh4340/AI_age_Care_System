import httpx

from .config import CHAT_MODEL, EMBED_MODEL, NUM_GPU, OLLAMA_URL


class OllamaError(Exception):
    """Something went wrong while talking to Ollama. The message is safe to show."""


def _post(path: str, payload: dict, timeout: float = 180) -> dict:
    try:
        response = httpx.post(f"{OLLAMA_URL}{path}", json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError as error:
        raise OllamaError(
            "Cannot reach Ollama. Open the Ollama app (or run 'ollama serve') and try again."
        ) from error
    except httpx.TimeoutException as error:
        raise OllamaError(
            "The model took too long. The first request is slow while it loads, so try again."
        ) from error
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:300]
        raise OllamaError(
            f"Ollama returned an error ({error.response.status_code}): {detail}. "
            "If it says the model was not found, run 'ollama pull' for that model."
        ) from error


# Two sets of model settings. The first is strict and repeatable (temperature 0).
# Small models sometimes get stuck repeating themselves with it, so if Ollama stops
# the answer for repeating, we try once more with a little randomness and a repeat penalty.
_STRICT = {"temperature": 0, "num_predict": 900, "num_ctx": 4096, "num_gpu": NUM_GPU}
_RETRY = {
    "temperature": 0.3,
    "repeat_penalty": 1.15,
    "seed": 1,
    "num_predict": 900,
    "num_ctx": 4096,
    "num_gpu": NUM_GPU,
}


def _chat_once(system: str, user: str, schema: dict, options: dict) -> str:
    data = _post(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "stream": False,
            "format": schema,  # Ollama only lets the model write JSON in this shape
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    return data["message"]["content"]


def chat_json(system: str, user: str, schema: dict) -> str:
    """Ask the small model a question and force the answer to match `schema`."""
    try:
        return _chat_once(system, user, schema, _STRICT)
    except OllamaError as error:
        if "repeat" not in str(error).lower():
            raise
        return _chat_once(system, user, schema, _RETRY)  # one more try, then give up


def embed(texts: list[str]) -> list[list[float]]:
    """Turn each text into a list of numbers that captures its meaning."""
    data = _post("/api/embed", {"model": EMBED_MODEL, "input": texts, "options": {"num_gpu": NUM_GPU}}, timeout=120)
    return data["embeddings"]


def is_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False
