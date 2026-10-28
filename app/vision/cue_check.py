"""Feature C: facial-cue check.

Gives a nurse a gentle prompt to look closer at a resident. It reads facial
muscle movements, turns them into a discomfort score, and maps the score to
low, medium or high.

Safety rules this module follows (from the team's privacy checklist):
  * It never names a disease, a cause or a medicine. Messages are fixed text.
  * It never saves the image. Images are decoded in memory and dropped.
  * It only returns numbers and a level, never a face crop or a faceprint.

How the score works
-------------------
MediaPipe Face Landmarker returns 52 "blendshape" scores between 0 and 1,
one per facial movement. We combine the ones that match the facial action
units (AUs) in the Prkachin and Solomon Pain Intensity scale (PSPI):

    PSPI = AU4 + max(AU6, AU7) + max(AU9, AU10) + AU43

    AU4  brow lowerer        -> browDownLeft / browDownRight
    AU6  cheek raiser        -> cheekSquintLeft / cheekSquintRight
    AU7  lid tightener       -> eyeSquintLeft / eyeSquintRight
    AU9  nose wrinkler       -> noseSneerLeft / noseSneerRight
    AU10 upper lip raiser    -> mouthUpperUpLeft / mouthUpperUpRight
    AU43 eyes closed         -> eyeBlinkLeft / eyeBlinkRight

Each term is 0..1 here, so the raw score is 0..4. We divide by 4 to get 0..1.

Smile gate: a broad smile also raises the cheeks (AU6) and the upper lip
(AU10), so a happy face scored "high" in our first test. A smile is AU12
(mouthSmile), which is not a pain cue, so we subtract the smile strength
from those two terms before adding them up.

The band thresholds below are a starting point. They must be checked on
volunteer photos (see scripts/evaluate_cue_check.py) and the chosen values
written up in the Feature C README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np

# Score bands. Below LOW_MAX is "low", below MEDIUM_MAX is "medium", else "high".
LOW_MAX = 0.25
MEDIUM_MAX = 0.45

# Eyes count as closed (AU43) only above this blink score, so a normal
# half-blink in a photo does not add to the score.
EYES_CLOSED_THRESHOLD = 0.6

# The only words this tool ever shows. No diagnosis, no cause, no medicine.
MESSAGES = {
    "low": "No change noticed. Keep to the usual care plan.",
    "medium": "Some signs of possible discomfort. Check in with the resident when you can.",
    "high": "Please look closer at this resident.",
    "no_face": "No face found. Try again with the face clear and well lit.",
    "multiple_faces": "More than one face found. Take the photo with only the resident in view.",
}

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task"


@dataclass
class CueResult:
    """What the cue check returns. Contains no image data."""

    status: str  # "ok", "no_face" or "multiple_faces"
    level: str | None = None  # "low", "medium", "high" when status is "ok"
    score: float | None = None  # 0..1 discomfort score
    cues: dict[str, float] = field(default_factory=dict)  # each PSPI term, 0..1
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "level": self.level,
            "score": None if self.score is None else round(self.score, 3),
            "cues": {k: round(v, 3) for k, v in self.cues.items()},
            "message": self.message,
        }


def _pair(bs: Mapping[str, float], name: str) -> float:
    """Average the left and right blendshape for one movement."""
    return (bs.get(f"{name}Left", 0.0) + bs.get(f"{name}Right", 0.0)) / 2


def pspi_terms(blendshapes: Mapping[str, float]) -> dict[str, float]:
    """Turn MediaPipe blendshapes into the four PSPI terms, each 0..1."""
    brow = _pair(blendshapes, "browDown")
    cheek = _pair(blendshapes, "cheekSquint")
    lid = _pair(blendshapes, "eyeSquint")
    nose = _pair(blendshapes, "noseSneer")
    lip = _pair(blendshapes, "mouthUpperUp")
    blink = _pair(blendshapes, "eyeBlink")
    smile = _pair(blendshapes, "mouthSmile")  # AU12, not a pain cue
    return {
        "brow_lowering": brow,  # AU4
        "eye_narrowing": max(0.0, max(cheek, lid) - smile),  # max(AU6, AU7), minus smile
        "nose_wrinkle_or_lip_raise": max(0.0, max(nose, lip) - smile),  # max(AU9, AU10), minus smile
        "eyes_closed": 1.0 if blink >= EYES_CLOSED_THRESHOLD else 0.0,  # AU43
    }


def level_for(score: float) -> str:
    if score < LOW_MAX:
        return "low"
    if score < MEDIUM_MAX:
        return "medium"
    return "high"


def score_blendshapes(
    blendshapes: Mapping[str, float],
    baseline: Mapping[str, float] | None = None,
) -> CueResult:
    """Score one face.

    ``baseline`` is optional: the same resident's PSPI terms from a calm,
    neutral photo. Faces differ at rest (some people always look a bit
    frowny), so subtracting a personal baseline cuts false alarms.
    """
    terms = pspi_terms(blendshapes)
    if baseline:
        terms = {k: max(0.0, v - baseline.get(k, 0.0)) for k, v in terms.items()}
    score = min(1.0, sum(terms.values()) / 4)
    level = level_for(score)
    return CueResult(status="ok", level=level, score=score, cues=terms, message=MESSAGES[level])


class FaceCueChecker:
    """Runs MediaPipe Face Landmarker on an image held in memory."""

    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH, max_faces: int = 2):
        # Imported here so the scoring code and its tests work without MediaPipe.
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Face model not found at {model_path}. Run: python scripts/download_models.py"
            )
        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            output_face_blendshapes=True,
            num_faces=max_faces,  # 2, so we can tell when a second person is in view
            # 0.7, not 0.5: in the face spike a dark photo gave a false second
            # face at 0.52 confidence. 0.7 drops it and keeps the real one (0.81).
            min_face_detection_confidence=0.7,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def check_rgb(self, rgb: np.ndarray, baseline: Mapping[str, float] | None = None) -> CueResult:
        """Check an RGB image array (height x width x 3, uint8)."""
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect(image)
        faces = result.face_blendshapes or []
        if not faces:
            return CueResult(status="no_face", message=MESSAGES["no_face"])
        if len(faces) > 1:
            return CueResult(status="multiple_faces", message=MESSAGES["multiple_faces"])
        blendshapes = {c.category_name: c.score for c in faces[0]}
        return score_blendshapes(blendshapes, baseline)

    def check_bytes(self, data: bytes, baseline: Mapping[str, float] | None = None) -> CueResult:
        """Check an uploaded JPEG or PNG. The bytes are never written to disk."""
        import cv2

        array = np.frombuffer(data, dtype=np.uint8)
        bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("The file is not a readable image.")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        try:
            return self.check_rgb(rgb, baseline)
        finally:
            del bgr, rgb, array  # drop the pixels straight away

    def close(self) -> None:
        self._landmarker.close()