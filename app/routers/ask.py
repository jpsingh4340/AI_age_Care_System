"""Ask AI page: nurse asks a question, picks a local Ollama model."""
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from app import config

router = APIRouter()
# full path so it works no matter which folder uvicorn starts from
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

OLLAMA_URL = getattr(config, "OLLAMA_URL", "http://localhost:11434")
NUM_GPU = getattr(config, "NUM_GPU", 0)

# these only make embeddings, they cant answer questions
EMBED_ONLY = ("nomic-embed", "mxbai-embed", "all-minilm", "bge-", "snowflake-arctic-embed")

GROUNDED_PROMPT = (
    "You help aged-care nurses. Answer ONLY using the approved guidance below. "
    "If the answer is not in the guidance, say: 'This is not in the approved guidance, "
    "please check with the RN in charge.' Never name or guess a disease or diagnosis. "
    "Keep it short and practical, max 6 sentences.\n\nApproved guidance:\n{context}"
)
GENERAL_PROMPT = (
    "You help aged-care nurses with general questions. Never name or guess a disease "
    "or diagnosis. Do not give medication doses. Keep it short, max 6 sentences, and "
    "end with: 'General answer only, check with the RN in charge.'"
)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    model: str | None = None


class AskOut(BaseModel):
    answer: str
    model: str
    grounded: bool
    sources: list[str] = []


def get_context(question: str) -> tuple[str, list[str]]:
    """Hook for Feature A. Return (guidance_text, source_titles).
    Empty text means nothing approved was found."""
    return "", []


async def installed_chat_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
    except httpx.HTTPError:
        return []
    names = [m["name"] for m in r.json().get("models", [])]
    return sorted(n for n in names if not n.startswith(EMBED_ONLY))


async def ask_ollama(model: str, messages: list[dict]) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_gpu": NUM_GPU, "temperature": 0.2},
    }
    # cpu can be slow, give it 3 min
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
    return r.json()["message"]["content"].strip()


@router.get("/ask", include_in_schema=False)
def ask_page():
    return FileResponse(STATIC_DIR / "ask.html")

@router.get("/ai-bubble.js", include_in_schema=False)
def ai_bubble():
    return FileResponse(STATIC_DIR / "ai-bubble.js", media_type="text/javascript")


@router.get("/api/ask/models")
async def list_models():
    models = await installed_chat_models()
    return {
        "ollama_running": bool(models),
        "default": config.CHAT_MODEL,
        "models": models,
    }


@router.post("/api/ask", response_model=AskOut)
async def ask(body: AskIn):
    models = await installed_chat_models()
    if not models:
        raise HTTPException(503, "Ollama is not running. Start it with: ollama serve")
    model = body.model or config.CHAT_MODEL
    if model not in models:
        raise HTTPException(400, f"Model '{model}' is not installed")

    context, sources = get_context(body.question)
    system = GROUNDED_PROMPT.format(context=context) if context else GENERAL_PROMPT
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": body.question},
    ]
    try:
        answer = await ask_ollama(model, messages)
    except httpx.TimeoutException:
        raise HTTPException(504, "The model took too long. Try a smaller model.")
    except httpx.HTTPError:
        raise HTTPException(502, "Ollama gave an error. Check the terminal running ollama.")
    return AskOut(answer=answer, model=model, grounded=bool(context), sources=sources)