"""Feature C page and API: face cue check, YOLO room monitor, and nurse alerts.

Photos and video frames are checked in memory and never saved.
Only the alert text and the nurse's decision are kept.
"""
import os
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import auth, guidance
from app.vision import alerts, suggestions
from app.vision.fall_monitor import FallConfig, PersonFrame, is_lying

router = APIRouter(tags=["Feature C: vision"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024

_checker = None
_live = {"running": False, "stop": False, "thread": None, "error": None,
         "frames": 0, "people": [], "skeleton": None}

# Which keypoints to join with a line to draw a stick figure (COCO order).
BONES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
         (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


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


def staff_name(x_role="", authorization="", x_session_token=""):
    """A signed-in carer or nurse. Returns their name, or "" if only X-Role was sent."""
    sess = auth.session_from_headers(authorization, x_session_token)
    if sess and sess["role"] in ("carer", "nurse"):
        return sess["full_name"]
    if x_role.strip().lower() in ("carer", "nurse"):
        return ""
    raise HTTPException(status_code=403, detail="Only a carer or a nurse can do this.")


def check_resident(resident_id):
    if resident_id is not None and guidance.load_resident(resident_id) is None:
        raise HTTPException(status_code=404, detail="There is no resident with that number.")


def draw_skeleton(people, shape):
    """A stick figure of each person on a plain background, as a JPEG.
    Only keypoints are drawn, so the picture never shows a face or the room."""
    import cv2
    import numpy as np

    height, width = shape
    scale = 480 / max(width, 1)
    canvas = np.full((int(height * scale), 480, 3), (58, 47, 12), dtype=np.uint8)
    for pid, bbox, kp in people:
        points = [(int(x * scale), int(y * scale), c) for x, y, c in kp]
        for a, b in BONES:
            if points[a][2] > 0.3 and points[b][2] > 0.3:
                cv2.line(canvas, points[a][:2], points[b][:2], (181, 193, 63), 3)
        for x, y, c in points:
            if c > 0.3:
                cv2.circle(canvas, (x, y), 4, (255, 255, 255), -1)
        cv2.putText(canvas, f"Person {pid}", (int(bbox[0] * scale), max(int(bbox[1] * scale) - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return cv2.imencode(".jpg", canvas)[1].tobytes()


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
    if result.level in ("medium", "high"):
        alert = alerts.add_alert("cue_check", f"{result.level}_cue", result.message,
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

    cfg = FallConfig(still_seconds=settings.still_seconds)

    def seen(t, people, shape):
        _live["frames"] += 1
        _live["people"] = [{"id": pid, "lying": is_lying(PersonFrame(t, bbox, kp), cfg)}
                           for pid, bbox, kp in people]
        _live["skeleton"] = draw_skeleton(people, shape)

    def work():
        try:
            for event in monitor.run(settings.camera_index, should_stop=lambda: _live["stop"], on_frame=seen):
                save_event(event, settings.resident_id)
        except Exception as error:
            _live["error"] = str(error)
        finally:
            _live["running"] = False

    _live.update(running=True, stop=False, error=None, frames=0, people=[], skeleton=None)
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
    """Is the camera on, how many frames were checked, and who is in view (standing or lying)."""
    return {key: _live[key] for key in ("running", "error", "frames", "people")}


@router.get("/api/vision/monitor/skeleton.jpg")
def monitor_skeleton():
    """The latest stick-figure picture (keypoints only, no camera image)."""
    if not _live["skeleton"]:
        raise HTTPException(status_code=404, detail="No picture yet.")
    return Response(content=_live["skeleton"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------- alerts and nurse outcomes ----------
@router.get("/api/vision/alerts")
def list_alerts(open_only: bool = False, resident_id: int | None = None):
    """Alerts, newest first. Each open alert comes with suggested next steps."""
    found = alerts.list_alerts(open_only, resident_id=resident_id)
    for alert in found:
        alert["suggestions"] = None if alert["outcome"] else suggestions.for_alert(alert)
        alert["followups"] = alerts.list_followups(alert_id=alert["id"])
    return found


@router.post("/api/vision/alerts/{alert_id}/ai-suggestions")
async def ai_suggestions(alert_id: int):
    """Ask the local AI to turn the care-plan lines into a short plan. Falls back to the care plan."""
    alert = alerts.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="There is no alert with that number.")
    return await run_in_threadpool(suggestions.ai_for_alert, alert)


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


# ---------- follow-ups for the carer ----------
class FollowupIn(BaseModel):
    instruction: str = Field(..., max_length=300)
    nurse: str = Field("", max_length=60)


@router.post("/api/vision/alerts/{alert_id}/send-to-carer", status_code=201)
def send_to_carer(alert_id: int, body: FollowupIn, x_role: str = Header(default=""),
                  authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Nurse only: ask the carers to do something for this alert's resident. Shows on the carer's My shift page."""
    name = nurse_name(x_role, authorization, x_session_token) or body.nurse.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Please type your name.")
    try:
        return alerts.send_to_carer(alert_id, body.instruction, name)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/api/vision/followups")
def list_followups(resident_id: int | None = None, open_only: bool = True, x_role: str = Header(default=""),
                   authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Carer or nurse: the nurse's follow-ups, newest first. Open ones only by default."""
    staff_name(x_role, authorization, x_session_token)
    return alerts.list_followups(resident_id=resident_id, open_only=open_only)


class FollowupDone(BaseModel):
    note: str = Field("", max_length=300)
    carer: str = Field("", max_length=60)


@router.post("/api/vision/followups/{followup_id}/done")
def followup_done(followup_id: int, body: FollowupDone, x_role: str = Header(default=""),
                  authorization: str = Header(default=""), x_session_token: str = Header(default="")):
    """Carer or nurse: tick off a follow-up. Saved in the audit log."""
    name = staff_name(x_role, authorization, x_session_token) or body.carer.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Please type your name.")
    try:
        return alerts.complete_followup(followup_id, name, body.note)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except alerts.AlreadyDecided as error:
        raise HTTPException(status_code=409, detail=str(error))
