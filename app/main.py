import re
import time
from pathlib import Path
from app.routers import ask, carer, decision, patient, vision

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool


from . import approval, auth, db, guidance, ocr, ollama_client, rag, records, slm
from .config import CHAT_MODEL, EMBED_MODEL
from .schemas import (
    AnalyseRequest,
    AnalyseResponse,
    ApprovedOut,
    AuditOut,
    AuthResponse,
    DecisionRequest,
    DraftOut,
    DraftSummary,
    GuidanceRequest,
    GuidanceResponse,
    LoginRequest,
    OcrResponse,
    RecordsOut,
    RegisterRequest,
    SavedReading,
    SaveReadingsRequest,
    UserOut,
)

auth.init_auth_db()

app = FastAPI(
    title="Age-Care Intelligence API",
    description="Student project. The AI summarises and flags, and a nurse approves.",
    version="0.2.0",
)

app.include_router(ask.router)
app.include_router(carer.router)
app.include_router(patient.router)
app.include_router(vision.router)
app.include_router(decision.router)

# Lets the React dashboard (on localhost, any port) call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")  # pictures used by the pages


def need_nurse(
    x_role: str = "",
    authorization: str = "",
    x_session_token: str = "",
) -> None:
    """Verifies that the caller has Registered Nurse privileges via role header or session token."""
    if isinstance(x_role, str) and x_role.strip().lower() == "nurse":
        return

    token = ""
    if isinstance(x_session_token, str) and x_session_token:
        token = x_session_token.strip()
    elif isinstance(authorization, str) and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    if token:
        sess = auth.get_session(token)
        if sess and sess["role"] == "nurse":
            return

    raise HTTPException(status_code=403, detail="Only a nurse can do this.")


# ---------- Pages ----------
@app.get("/", include_in_schema=False)
def home():
    """The dashboard. Open http://127.0.0.1:8000 in the browser."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/nurse", include_in_schema=False)
def nurse_page():
    """The nurse clinical dashboard."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/welcome", include_in_schema=False)
def welcome_page():
    """The landing page that explains the project."""
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/guidance", include_in_schema=False)
def guidance_page():
    """The draft guidance screen (the dashboard is the home page at /)."""
    return FileResponse(STATIC_DIR / "guidance.html")


@app.get("/ocr", include_in_schema=False)
def ocr_page():
    """The health report screen."""
    return FileResponse(STATIC_DIR / "ocr.html")


@app.get("/login", include_in_schema=False)
def login_page():
    """Authentication and registration page."""
    return FileResponse(STATIC_DIR / "login.html")


# ---------- Authentication & Registration API ----------
@app.post("/api/auth/register", response_model=AuthResponse)
def auth_register(request: RegisterRequest):
    """Register a new user as either a nurse or carer."""
    try:
        user = auth.register_user(request.username, request.password, request.full_name, request.role)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return auth.create_session(user)


@app.post("/api/auth/login", response_model=AuthResponse)
def auth_login(request: LoginRequest):
    """Authenticate with username and password, returning a session token."""
    user = auth.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return auth.create_session(user)


@app.get("/api/auth/me", response_model=UserOut)
def auth_me(
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Get current authenticated user profile."""
    token = x_session_token.strip() if x_session_token else ""
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    sess = auth.get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return UserOut(
        username=sess["username"],
        full_name=sess["full_name"],
        role=sess["role"],
    )


@app.post("/api/auth/logout")
def auth_logout(
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Invalidate session token."""
    token = x_session_token.strip() if x_session_token else ""
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if token:
        auth.delete_session(token)
    return {"ok": True}


# ---------- Basic API ----------
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


# ---------- Feature A: guidance ----------
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

    resident, sources, watch_for, prevention, dropped, gaps = result
    conditions = [c["name"] for c in resident["conditions"]]
    draft_id = db.save_draft(
        resident["resident_id"],
        CHAT_MODEL,
        {
            "resident": resident["name"],
            "conditions": conditions,
            "watch_for": [line.model_dump() for line in watch_for],
            "prevention": [line.model_dump() for line in prevention],
            "dropped": [line.model_dump() for line in dropped],
            "gaps": gaps,
            "sources": [source.model_dump() for source in sources],
        },
    )
    return GuidanceResponse(
        resident=resident["name"],
        conditions=conditions,
        watch_for=watch_for,
        prevention=prevention,
        dropped=dropped,
        gaps=gaps,
        sources=sources,
        model=CHAT_MODEL,
        seconds=round(time.perf_counter() - started, 1),
        draft_id=draft_id,
    )


# ---------- OCR ----------
MAX_IMAGE_BYTES = 6 * 1024 * 1024


@app.post("/api/ocr/extract", response_model=OcrResponse)
async def ocr_extract(file: UploadFile):
    """Read a photo of a fake health report. The values are drafts until a nurse checks them."""
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="The image is too big. Use a photo under 6 MB.")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpg = data.startswith(b"\xff\xd8\xff")
    if not (is_png or is_jpg):
        raise HTTPException(status_code=400, detail="Please upload a PNG or JPG image.")

    started = time.perf_counter()
    try:
        lines = await run_in_threadpool(ocr.read_lines, data)
    except ocr.OcrError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=422, detail="The OCR could not read this image.") from error

    return OcrResponse(
        readings=ocr.extract_readings(lines),
        lines=lines,
        seconds=round(time.perf_counter() - started, 1),
    )


# ---------- Nurse approval ----------
@app.get("/api/guidance/pending", response_model=list[DraftSummary])
def pending_drafts(
    x_role: str = Header(default=""),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Drafts waiting for a nurse. Nurse only."""
    need_nurse(x_role, authorization, x_session_token)
    return [
        DraftSummary(
            draft_id=d["draft_id"],
            resident_id=d["resident_id"],
            resident=d["resident"],
            created_at=d["created_at"],
            lines=len(d["watch_for"]) + len(d["prevention"]),
        )
        for d in db.list_drafts("draft")
    ]


@app.get("/api/guidance/draft/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: int,
    x_role: str = Header(default=""),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """One saved draft. Nurse only."""
    need_nurse(x_role, authorization, x_session_token)
    draft = db.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return draft


@app.post("/api/guidance/draft/{draft_id}/decision", response_model=DraftOut)
def decide_draft(
    draft_id: int,
    request: DecisionRequest,
    x_role: str = Header(default=""),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """A nurse approves (optionally with edits) or rejects a draft."""
    need_nurse(x_role, authorization, x_session_token)
    draft = db.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found.")

    if request.decision == "approve":
        try:
            content, detail = approval.final_content(draft, request)
        except approval.ApprovalError as error:
            raise HTTPException(status_code=422, detail=str(error))
    else:
        content = {key: draft[key] for key in ("resident", "conditions", "watch_for", "prevention", "dropped", "sources")}
        detail = "The nurse rejected the draft."
        if request.note:
            detail += f" Reason: {request.note}"

    try:
        db.decide(draft_id, request.decision, request.reviewer.strip(), request.note, content, detail)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return db.get_draft(draft_id)


@app.get("/api/guidance/{resident_id}/approved", response_model=ApprovedOut)
def approved_guidance(resident_id: int):
    """What carers see: only guidance a nurse has approved."""
    draft = db.latest_approved(resident_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No approved guidance for this resident yet.")
    return ApprovedOut(
        draft_id=draft["draft_id"],
        resident_id=draft["resident_id"],
        resident=draft["resident"],
        approved_by=draft["reviewed_by"],
        approved_at=draft["reviewed_at"],
        note=draft["review_note"] or "",
        watch_for=draft["watch_for"],
        prevention=draft["prevention"],
    )


@app.get("/api/audit", response_model=list[AuditOut])
def audit_log(
    limit: int = 50,
    x_role: str = Header(default=""),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Who did what, and when. Nurse only."""
    need_nurse(x_role, authorization, x_session_token)
    return db.audit_entries(min(max(limit, 1), 200))


# ---------- Saved health values and resident records ----------
@app.post("/api/residents/{resident_id}/readings", response_model=list[SavedReading])
def save_readings(
    resident_id: int,
    request: SaveReadingsRequest,
    x_role: str = Header(default=""),
    authorization: str = Header(default=""),
    x_session_token: str = Header(default=""),
):
    """Save values a nurse has checked against the photo. Only a nurse can save."""
    need_nurse(x_role, authorization, x_session_token)
    if guidance.load_resident(resident_id) is None:
        raise HTTPException(status_code=404, detail="There is no resident with that number.")

    date = request.report_date.strip()
    if date and not re.fullmatch(ocr.VALUE_FORMATS["report_date"], date):
        raise HTTPException(status_code=422, detail=f'"{date}" is not a valid report date.')

    keys = [item.key for item in request.readings]
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=422, detail="Each value can only be saved once at a time.")

    items = []
    for item in request.readings:
        problem = ocr.value_error(item.key, item.value)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        label, unit = ocr.FIELD_INFO[item.key]
        items.append({"key": item.key, "label": label, "value": item.value.strip(), "unit": unit})

    db.save_readings(resident_id, request.reviewer.strip(), date, items)
    return db.list_readings(resident_id)[: len(items)]


@app.get("/api/residents/{resident_id}/readings", response_model=list[SavedReading])
def get_readings(resident_id: int):
    """The values nurses have checked and saved, newest first."""
    if guidance.load_resident(resident_id) is None:
        raise HTTPException(status_code=404, detail="There is no resident with that number.")
    return db.list_readings(resident_id)


@app.get("/api/residents/{resident_id}/records", response_model=RecordsOut)
def resident_records(resident_id: int):
    """Fake records for the doctor summary: allergies, contacts, today's care record, concerns."""
    found = records.build_records(resident_id)
    if found is None:
        raise HTTPException(status_code=404, detail="There is no resident with that number.")
    return found