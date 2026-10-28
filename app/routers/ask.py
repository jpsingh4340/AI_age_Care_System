"""Ask AI page: nurse asks a question, picks a local Ollama model."""
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
    resident_id: int | str | None = None


class AskOut(BaseModel):
    answer: str
    model: str
    grounded: bool
    sources: list[str] = []


async def get_context(request: Request, resident_id, role: str | None) -> tuple[str, list[str]]:
    """Feature A: get the nurse-approved guidance for this resident.
    Calls our own guidance API inside the app (no network), so it uses the same rules.
    Returns (guidance_text, sources). Empty text means nothing approved yet."""
    if resident_id is None:
        return "", []
    headers = {"X-Role": role or "carer"}
    transport = httpx.ASGITransport(app=request.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
            approved = await client.get(f"/api/guidance/{resident_id}/approved", headers=headers)
            people = await client.get("/api/residents", headers=headers)
    except httpx.HTTPError:
        return "", []
    guide = approved.json() if approved.status_code == 200 else None
    if not guide:
        return "", []

    name = "this resident"
    if people.status_code == 200:
        for person in people.json():
            if str(person.get("resident_id")) == str(resident_id):
                name = person.get("name", name)
    # only the approved lines go to the model, no conditions or diagnosis
    watch = guide.get("watch_for", [])
    prevent = guide.get("prevention", [])
    lines = [f"Resident: {name}", "Signs to watch for:"]
    lines += [f"- {line['text']}" for line in watch]
    lines += ["Prevention steps:"]
    lines += [f"- {line['text']}" for line in prevent]

    sources = [f"Approved by {guide.get('approved_by', 'a nurse')}"]
    for line in watch + prevent:
        src = "Written by a nurse" if line.get("edited") else line.get("source")
        if src and src not in sources:
            sources.append(src)
    return "\n".join(lines), sources[:5]


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
async def ask(body: AskIn, request: Request, x_role: str | None = Header(None)):
    models = await installed_chat_models()
    if not models:
        raise HTTPException(503, "Ollama is not running. Start it with: ollama serve")
    model = body.model or (config.CHAT_MODEL if config.CHAT_MODEL in models else models[0])
    if model not in models:
        raise HTTPException(400, f"Model '{model}' is not installed")

    context, sources = await get_context(request, body.resident_id, x_role)
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