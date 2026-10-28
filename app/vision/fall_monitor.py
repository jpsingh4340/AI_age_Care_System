"""Feature C: YOLO room monitor for falls and long stillness.

YOLO11n-pose finds each person in a video frame and 17 body keypoints
(COCO order). Simple, explainable rules then decide if someone has fallen
or has not moved for a long time.

Privacy rules:
  * Frames are analysed in memory and dropped. Nothing is recorded.
  * Only an event row is kept: time, camera, event type, confidence.
  * The alert asks a nurse to check. It never says what is wrong.

The rule code (FallDetector) has no YOLO or OpenCV dependency, so it can be
unit tested with made-up keypoints.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

# COCO keypoint indexes used by the rules.
L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "yolo11n-pose.pt"

ALERT_TEXT = {
    "possible_fall": "Possible fall. Please check on the resident now.",
    "no_movement": "No movement for a while. Please check on the resident.",
}


@dataclass
class FallConfig:
    """Thresholds for the rules. Tune these with scripts/evaluate_falls.py."""

    lying_aspect: float = 1.0  # box width / height above this looks lying down
    lying_torso_angle: float = 60.0  # torso this many degrees from upright looks lying down
    drop_window_s: float = 1.5  # a fall is a fast drop within this many seconds...
    drop_fraction: float = 0.25  # ...of at least this share of the standing body height
    confirm_lying_s: float = 2.0  # still lying this long after the drop = fall
    reset_upright_s: float = 2.0  # upright this long = ready to detect a new fall
    still_seconds: float = 600.0  # no movement this long = no-movement alert (10 min)
    still_threshold: float = 0.02  # mean keypoint movement per second, as share of body height
    min_keypoint_conf: float = 0.3


@dataclass
class Event:
    event_type: str  # "possible_fall" or "no_movement"
    person_id: int
    timestamp: float  # seconds (video time, or wall clock for a live camera)
    confidence: float
    camera: str = "camera-1"
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PersonFrame:
    """One person in one frame. bbox = (x1, y1, x2, y2); keypoints = 17 x 3 (x, y, conf)."""

    t: float
    bbox: tuple[float, float, float, float]
    keypoints: np.ndarray


@dataclass
class _Track:
    history: deque = field(default_factory=lambda: deque(maxlen=600))
    lying_since: float | None = None
    upright_since: float | None = None
    fall_reported: bool = False
    drop_seen_at: float | None = None
    drop_size: float = 0.0
    still_since: float | None = None
    still_reported: bool = False


def torso_angle(kp: np.ndarray, min_conf: float = 0.3) -> float | None:
    """Degrees between the torso (mid-shoulder to mid-hip) and straight up. None if unsure."""
    pts = kp[[L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]]
    if np.any(pts[:, 2] < min_conf):
        return None
    shoulder = pts[:2, :2].mean(axis=0)
    hip = pts[2:, :2].mean(axis=0)
    dx, dy = shoulder - hip
    if dx == 0 and dy == 0:
        return None
    # Image y grows downward, so upright means the shoulder is above the hip (dy < 0).
    # 0 = upright, 90 = flat, 180 = upside down.
    return math.degrees(math.atan2(abs(dx), -dy))


def hip_y(kp: np.ndarray, min_conf: float = 0.3) -> float | None:
    hips = kp[[L_HIP, R_HIP]]
    if np.any(hips[:, 2] < min_conf):
        return None
    return float(hips[:, 1].mean())


def is_lying(frame: PersonFrame, cfg: FallConfig) -> bool:
    x1, y1, x2, y2 = frame.bbox
    w, h = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
    angle = torso_angle(frame.keypoints, cfg.min_keypoint_conf)
    if angle is not None:
        return angle >= cfg.lying_torso_angle or w / h >= cfg.lying_aspect * 1.3
    return w / h >= cfg.lying_aspect


class FallDetector:
    """Feeds on one person-frame at a time and returns any new events."""

    def __init__(self, cfg: FallConfig | None = None, camera: str = "camera-1"):
        self.cfg = cfg or FallConfig()
        self.camera = camera
        self.tracks: dict[int, _Track] = {}

    def update(self, person_id: int, frame: PersonFrame) -> list[Event]:
        cfg = self.cfg
        tr = self.tracks.setdefault(person_id, _Track())
        events: list[Event] = []
        lying = is_lying(frame, cfg)

        # 1. Look for a fast drop of the hips compared with recent upright frames.
        hy = hip_y(frame.keypoints, cfg.min_keypoint_conf)
        if hy is not None:
            recent = [
                (p.t, hip_y(p.keypoints, cfg.min_keypoint_conf), p.bbox[3] - p.bbox[1])
                for p in tr.history
                if frame.t - p.t <= cfg.drop_window_s and not is_lying(p, cfg)
            ]
            recent = [(t, y, h) for t, y, h in recent if y is not None]
            if recent:
                top_y = min(y for _, y, _ in recent)
                body_h = max(h for _, _, h in recent)
                drop = (hy - top_y) / max(body_h, 1e-6)
                if drop >= cfg.drop_fraction:
                    tr.drop_seen_at = frame.t
                    tr.drop_size = max(tr.drop_size, drop)

        # 2. Lying after a recent drop, for long enough = possible fall.
        if lying:
            tr.upright_since = None
            if tr.lying_since is None:
                tr.lying_since = frame.t
            dropped_recently = (
                tr.drop_seen_at is not None
                and tr.lying_since - tr.drop_seen_at <= cfg.drop_window_s
            )
            if (
                not tr.fall_reported
                and dropped_recently
                and frame.t - tr.lying_since >= cfg.confirm_lying_s
            ):
                conf = min(1.0, 0.5 + tr.drop_size)
                events.append(self._event("possible_fall", person_id, frame.t, conf))
                tr.fall_reported = True
        else:
            tr.lying_since = None
            if tr.upright_since is None:
                tr.upright_since = frame.t
            if frame.t - tr.upright_since >= cfg.reset_upright_s:
                tr.fall_reported = False
                tr.drop_seen_at = None
                tr.drop_size = 0.0

        # 3. Stillness: mean keypoint movement per second, scaled by body size.
        if tr.history:
            prev = tr.history[-1]
            dt = max(frame.t - prev.t, 1e-6)
            ok = (frame.keypoints[:, 2] >= cfg.min_keypoint_conf) & (prev.keypoints[:, 2] >= cfg.min_keypoint_conf)
            if ok.any():
                body = max(frame.bbox[3] - frame.bbox[1], frame.bbox[2] - frame.bbox[0], 1e-6)
                move = np.linalg.norm(frame.keypoints[ok, :2] - prev.keypoints[ok, :2], axis=1).mean() / body / dt
                if move < cfg.still_threshold:
                    if tr.still_since is None:
                        tr.still_since = prev.t
                    if not tr.still_reported and frame.t - tr.still_since >= cfg.still_seconds:
                        events.append(self._event("no_movement", person_id, frame.t, 0.7))
                        tr.still_reported = True
                else:
                    tr.still_since = None
                    tr.still_reported = False

        tr.history.append(frame)
        return events

    def _event(self, kind: str, pid: int, t: float, conf: float) -> Event:
        return Event(kind, pid, round(t, 2), round(conf, 2), self.camera, ALERT_TEXT[kind])


class PoseMonitor:
    """Runs YOLO pose tracking on a camera or a video file and yields events.

    ``source`` is a webcam number (0) or a video file path. Frames stay in
    memory only. ``frame_stride`` skips frames to keep a laptop CPU up to speed.
    """

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        cfg: FallConfig | None = None,
        camera: str = "camera-1",
        frame_stride: int = 2,
        min_person_conf: float = 0.5,
    ):
        from ultralytics import YOLO

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"YOLO model not found at {model_path}. Run: python scripts/download_models.py"
            )
        self.model = YOLO(str(model_path))
        self.detector = FallDetector(cfg, camera)
        self.frame_stride = max(1, frame_stride)
        self.min_person_conf = min_person_conf

    def people_in(self, bgr: np.ndarray) -> list[tuple[int, tuple, np.ndarray]]:
        """Return (track id, bbox, keypoints) for each person YOLO finds in one frame."""
        res = self.model.track(bgr, persist=True, verbose=False, classes=[0])[0]
        out = []
        if res.boxes is None or res.keypoints is None:
            return out
        boxes = res.boxes.xyxy.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        ids = res.boxes.id.cpu().numpy().astype(int) if res.boxes.id is not None else np.arange(len(boxes))
        kxy = res.keypoints.xy.cpu().numpy()
        kconf = res.keypoints.conf.cpu().numpy() if res.keypoints.conf is not None else np.ones(kxy.shape[:2])
        for i in range(len(boxes)):
            if confs[i] < self.min_person_conf:
                continue
            kp = np.concatenate([kxy[i], kconf[i][:, None]], axis=1)
            out.append((int(ids[i]), tuple(float(v) for v in boxes[i]), kp))
        return out

    def run(
        self,
        source: int | str,
        should_stop: Callable[[], bool] = lambda: False,
        live: bool | None = None,
    ) -> Iterator[Event]:
        import cv2

        live = isinstance(source, int) if live is None else live
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source {source!r}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        start = time.time()
        index = 0
        try:
            while not should_stop():
                ok, frame = cap.read()
                if not ok:
                    break
                index += 1
                if index % self.frame_stride:
                    continue
                t = time.time() - start if live else index / fps
                for pid, bbox, kp in self.people_in(frame):
                    yield from self.detector.update(pid, PersonFrame(t, bbox, kp))
                del frame  # nothing is kept
        finally:
            cap.release()