"""Feature C API tests. Fake models, so no camera, MediaPipe or YOLO is needed."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import vision
from app.vision import alerts
from app.vision.cue_check import CueResult, score_blendshapes
from app.vision.fall_monitor import Event

client = TestClient(app)
NURSE = {"X-Role": "nurse"}
CARER = {"X-Role": "carer"}
PHOTO = {"file": ("face.jpg", b"jpeg bytes", "image/jpeg")}

HIGH = score_blendshapes({"browDownLeft": 0.9, "browDownRight": 0.9, "eyeSquintLeft": 0.8,
                          "eyeSquintRight": 0.8, "noseSneerLeft": 0.6, "noseSneerRight": 0.6})
LOW = score_blendshapes({})


class FakeChecker:
    def __init__(self, result):
        self.result = result

    def check_bytes(self, data, baseline=None):
        if data == b"not an image":
            raise ValueError("The file is not a readable image.")
        return self.result


class FakeMonitor:
    def run(self, source, should_stop=lambda: False, live=None):
        yield Event("possible_fall", 1, 4.2, 0.83, "test-clip", "Possible fall. Please check on the resident now.")


@pytest.fixture
def use_checker():
    def use(result):
        app.dependency_overrides[vision.get_checker] = lambda: FakeChecker(result)
    yield use
    app.dependency_overrides.clear()


@pytest.fixture
def fake_yolo():
    app.dependency_overrides[vision.get_monitor_factory] = lambda: (lambda cfg, camera: FakeMonitor())
    yield
    app.dependency_overrides.clear()


def test_page_loads():
    r = client.get("/vision")
    assert r.status_code == 200 and "Face and room check" in r.text


def test_high_cue_makes_an_alert(use_checker):
    use_checker(HIGH)
    r = client.post("/api/vision/cue-check", files=PHOTO, data={"resident_id": "2"})
    assert r.status_code == 200 and r.json()["level"] == "high"
    alert = client.get("/api/vision/alerts").json()[0]
    assert alert["alert_type"] == "high_cue" and alert["resident_id"] == 2
    assert alert["id"] == r.json()["alert_id"]


def test_low_cue_makes_no_alert(use_checker):
    use_checker(LOW)
    r = client.post("/api/vision/cue-check", files=PHOTO)
    assert r.json()["level"] == "low"
    assert client.get("/api/vision/alerts").json() == []


def test_no_face_and_bad_image(use_checker):
    use_checker(CueResult(status="no_face", message="No face found."))
    assert client.post("/api/vision/cue-check", files=PHOTO).json()["status"] == "no_face"
    bad = client.post("/api/vision/cue-check", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 400


def test_unknown_resident_is_404(use_checker):
    use_checker(HIGH)
    assert client.post("/api/vision/cue-check", files=PHOTO, data={"resident_id": "99"}).status_code == 404


def test_clip_alerts_saved_and_video_deleted(fake_yolo, tmp_path, monkeypatch):
    import tempfile
    videos = tmp_path / "videos"
    videos.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(videos))
    r = client.post("/api/vision/monitor/clip", files={"file": ("fall.mp4", b"video", "video/mp4")},
                    data={"resident_id": "2"})
    assert r.status_code == 200 and r.json()["count"] == 1
    assert client.get("/api/vision/alerts").json()[0]["alert_type"] == "possible_fall"
    assert list(videos.iterdir()) == []  # the uploaded video is gone


def test_only_a_nurse_can_decide():
    alert = alerts.add_alert("cue_check", "high_cue", "Please look closer at this resident.", resident_id=1)
    url = f"/api/vision/alerts/{alert['id']}/decision"
    body = {"outcome": "fine", "nurse": "Nurse Sam"}
    assert client.post(url, json=body, headers=CARER).status_code == 403
    r = client.post(url, json=body, headers=NURSE)
    assert r.status_code == 200 and r.json()["decided_by"] == "Nurse Sam"
    assert client.get("/api/vision/alerts", params={"open_only": True}).json() == []


def test_action_taken_needs_a_note():
    alert = alerts.add_alert("room_monitor", "possible_fall", "Possible fall.", resident_id=2)
    url = f"/api/vision/alerts/{alert['id']}/decision"
    r = client.post(url, json={"outcome": "action_taken", "nurse": "Sam"}, headers=NURSE)
    assert r.status_code == 422
    r = client.post(url, json={"outcome": "action_taken", "note": "Helped back to bed", "nurse": "Sam"}, headers=NURSE)
    assert r.status_code == 200 and r.json()["outcome_note"] == "Helped back to bed"


def test_unknown_outcome_and_second_decision_rejected():
    alert = alerts.add_alert("room_monitor", "no_movement", "No movement.", resident_id=3)
    url = f"/api/vision/alerts/{alert['id']}/decision"
    assert client.post(url, json={"outcome": "ignore", "nurse": "Sam"}, headers=NURSE).status_code == 422
    assert client.post(url, json={"outcome": "false_alarm", "nurse": "Sam"}, headers=NURSE).status_code == 200
    assert client.post(url, json={"outcome": "fine", "nurse": "Sam"}, headers=NURSE).status_code == 409
    assert client.post("/api/vision/alerts/999/decision", json={"outcome": "fine", "nurse": "Sam"},
                       headers=NURSE).status_code == 404


def test_decision_goes_in_the_audit_log():
    alert = alerts.add_alert("room_monitor", "possible_fall", "Possible fall.", resident_id=2)
    client.post(f"/api/vision/alerts/{alert['id']}/decision",
                json={"outcome": "escalated", "note": "Called the GP", "nurse": "Sam"}, headers=NURSE)
    log = client.get("/api/audit", headers=NURSE).json()
    assert any(e["action"] == "vision_decision" and "Called the GP" in e["detail"] for e in log)


def test_live_camera_is_nurse_only():
    assert client.post("/api/vision/monitor/start", json={}, headers=CARER).status_code == 403


def test_alert_messages_never_name_a_disease():
    from app.vision.cue_check import MESSAGES
    from app.vision.fall_monitor import ALERT_TEXT
    words = " ".join(list(MESSAGES.values()) + list(ALERT_TEXT.values()) + list(alerts.OUTCOMES.values())).lower()
    for banned in ["dementia", "stroke", "fracture", "infection", "delirium", "paracetamol", "mg"]:
        assert banned not in words.split()