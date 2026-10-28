"""Feature C page and API: face cue check, YOLO room monitor, and nurse alerts.

Photos and video frames are checked in memory and never saved.
Only the alert text and the nurse's decision are kept.
"""
import os
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import auth, guidance
from app.vision import alerts
from app.vision.fall_monitor import FallConfig

router = APIRouter(tags=["Feature C: vision"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024

_checker = None
_live = {"running": False, "stop": False, "thread": None, "error": None}


# ---------- helpers ----------
def get_checker():
    """Load the face model once, on first use."""
    global _checker
    if _checker is None:
        try:
            from app.vision.cue_check import FaceCueChecker
            _checker = FaceCueChecker()
        except (ImportError, FileNotFoundError) as error:
            raise HTTPException(status_code=503, detail=f"The face check is not set up: {error}")
    return _checker


def make_monitor(cfg, camera):
    try:
        from app.vision.fall_monitor import PoseMonitor
        return PoseMonitor(cfg=cfg, camera=camera)
    except ImportError:
        raise HTTPException(status_code=503, detail="YOLO is not installed. Run: python -m pip install ultralytics lap")
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error))


def get_monitor_factory():
    return make_monitor


def nurse_name(x_role="", authorization="", x_session_token=""):
    """Same check as the rest of the app. Returns the nurse's name, or "" if only X-Role was sent."""
    token = (x_session_token or "").strip()
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if token:
        sess = auth.get_session(token)
        if sess and sess["role"] == "nurse":
            return sess["full_name"]
    if x_role.strip().lower() == "nurse":
        return ""
    raise HTTPException(status_code=403, detail="Only a nurse can do this.")


def check_resident(resident_id):
    if resident_id is not None and guidance.load_resident(resident_id) is None:
        raise HTTPException(status_code=404, detail="There is no resident with that number.")


def save_event(event, resident_id=None):
    alerts.add_alert("room_monitor", event.event_type, event.message,
                     resident_id=resident_id, camera=event.camera, confidence=round(event.confidence, 2))


# ---------- page ----------
@router.get("/vision", include_in_schema=False)
def vision_page():
    return FileResponse(STATIC_DIR / "vision.html")


# ---------- face cue check ----------
@router.post("/api/vision/cue-check")
async def cue_check(file: UploadFile = File(...), resident_id: int | None = Form(None),
                    checker=Depends(get_checker)):
    """Photo of a consenting volunteer -> low, medium or high. High makes an alert for the nurse."""
    check_resident(resident_id)
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="The photo is too big. Use a photo under 6 MB.")
    try:
        result = await run_in_threadpool(checker.check_bytes, data)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    finally:
        del data  # the photo is never saved
    body = result.to_dict()
    if result.level == "high":
        alert = alerts.add_alert("cue_check", "high_cue", result.message,
                                 resident_id=resident_id, confidence=round(result.score, 2))
        body["alert_id"] = alert["id"]
    return body


# ---------- room monitor (YOLO) ----------
@router.post("/api/vision/monitor/clip")
async def monitor_clip(file: UploadFile = File(...), resident_id: int | None = Form(None),
                       still_seconds: float = Form(20), factory=Depends(get_monitor_factory)):
    """Check a test video for a possible fall or no movement. The video is deleted straight after."""
    check_resident(resident_id)
    data = await file.read()
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="The video is too big. Use a clip under 100 MB.")
    monitor = factory(FallConfig(still_seconds=still_seconds), "test-clip")
    suffix = Path(file.filename or "clip.mp4").suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # OpenCV can only read a file
    try:
        tmp.write(data)
        tmp.close()
        del data
        events = await run_in_threadpool(lambda: list(monitor.run(tmp.name, live=False)))
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    finally:
        os.unlink(tmp.name)
    for event in events:
        save_event(event, resident_id)
    return {"count": len(events), "events": [e.to_dict() for e in events]}


class LiveSettings(BaseModel):
    camera_index: int = Field(0, ge=0, le=5)
    resident_id: int | None = None
    still_seconds: float = Field(600, ge=5, le=3600)


@router.post("/api/vision/monitor/start")
def monitor_start(settings: LiveSettings, factory=Depends(get_monitor_factory),
                  x_role: str = Header(default=""), authorization: str = Header(default=""),
                  x_session_token: str = Header(default="")):
    """Nurse only. Watch the laptop camera in the background. Nothing is recorded."""
    nurse_name(x_role, authorization, x_session_token)
    check_resident(settings.resident_id)
    if _live["running"]:
        raise HTTPException(status_code=409, detail="The camera is already running.")
    monitor = factory(FallConfig(still_seconds=settings.still_seconds), f"camera-{settings.camera_index}")

    def work():
        try:
            for event in monitor.run(settings.camera_index, should_stop=lambda: _live["stop"]):
                save_event(event, settings.resident_id)
        except Exception as error:
            _live["error"] = str(error)
        finally:
            _live["running"] = False

    _live.update(running=True, stop=False, error=None)
    _live["thread"] = threading.Thread(target=work, daemon=True)
    _live["thread"].start()
    return {"running": True}


@router.post("/api/vision/monitor/stop")
def monitor_stop(x_role: str = Header(default=""), authorization: str = Header(default=""),
                 x_session_token: str = Header(default="")):
    nurse_name(x_role, authorization, x_session_token)
    _live["stop"] = True
    if _live["thread"] is not None:
        _live["thread"].join(timeout=5)
    return {"running": _live["running"]}


@router.get("/api/vision/monitor/status")
def monitor_status():
    return {"running": _live["running"], "error": _live["error"]}


# ---------- alerts and nurse outcomes ----------
@router.get("/api/vision/alerts")
def list_alerts(open_only: bool = False):
    """Alerts, newest first. open_only=true shows the ones still waiting for a nurse."""
    return alerts.list_alerts(open_only)


@router.get("/api/vision/outcomes")
def outcomes():
    return {"outcomes": alerts.OUTCOMES, "note_needed": sorted(alerts.NOTE_NEEDED)}


class AlertDecision(BaseModel):
    outcome: str
    note: str = Field("", max_length=300)
    nurse: str = Field("", max_length=60)


@router.post("/api/vision/alerts/{alert_id}/decision")
def decide(alert_id: int, body: AlertDecision, x_role: str = Header(default=""),
           authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Nurse only: fine, action_taken, false_alarm or escalated. Saved in the audit log."""
    name = nurse_name(x_role, authorization, x_session_token) or body.nurse.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Please type your name.")
    try:
        return alerts.decide_alert(alert_id, body.outcome, name, body.note)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except alerts.AlreadyDecided as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))