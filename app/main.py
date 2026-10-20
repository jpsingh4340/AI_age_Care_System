import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import guidance, ollama_client, rag, slm
from .config import CHAT_MODEL, EMBED_MODEL
from .schemas import AnalyseRequest, AnalyseResponse, GuidanceRequest, GuidanceResponse

app = FastAPI(
    title="Age-Care Intelligence API",
    description="Student project. Fake data only. The AI summarises and flags, and a nurse approves.",
    version="0.1.0",
)

# Lets the React dashboard (on localhost, any port) call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def home():
    """The simple web screen. Open http://127.0.0.1:8000 in the browser."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/residents")
def residents():
    """The fake residents and their recorded conditions."""
    return guidance.list_residents()


@app.get("/api/health")
def health():
    """Quick check that the API is running and Ollama is reachable."""
    return {
        "api": "ok",
        "ollama_running": ollama_client.is_up(),
        "chat_model": CHAT_MODEL,
        "embed_model": EMBED_MODEL,
    }


@app.post("/api/analyse", response_model=AnalyseResponse)
def analyse(request: AnalyseRequest):
    """Turn a carer's note into a draft summary, flags, and a care plan check."""
    started = time.perf_counter()
    try:
        analysis, dropped = slm.analyse_note(request.note)

        plan_checks, retrieved = [], []
        if request.use_rag:
            plan_checks, retrieved = rag.check_plan(request.resident_id, request.note)
    except ollama_client.OllamaError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return AnalyseResponse(
        summary=analysis.summary,
        flags=analysis.flags,
        dropped_flags=dropped,
        plan_checks=plan_checks,
        retrieved=retrieved,
        model=CHAT_MODEL,
        seconds=round(time.perf_counter() - started, 1),
    )


@app.post("/api/guidance/draft", response_model=GuidanceResponse)
def guidance_draft(request: GuidanceRequest):
    """Feature A: draft symptoms to watch for and prevention steps for one resident.

    This is only a draft. Nothing is shown to carers until a nurse approves it.
    """
    started = time.perf_counter()
    try:
        result = guidance.draft_guidance(request.resident_id)
    except ollama_client.OllamaError as error:
        raise HTTPException(status_code=503, detail=str(error))
    if result is None:
        raise HTTPException(status_code=404, detail="Resident not found.")

    resident, sources, watch_for, prevention, dropped = result
    return GuidanceResponse(
        resident=resident["name"],
        conditions=[c["name"] for c in resident["conditions"]],
        watch_for=watch_for,
        prevention=prevention,
        dropped=dropped,
        sources=sources,
        model=CHAT_MODEL,
        seconds=round(time.perf_counter() - started, 1),
    )
