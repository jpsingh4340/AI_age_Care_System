"""Download the two model files Feature C needs into ./models.

    python scripts/download_models.py
"""

import urllib.request
from pathlib import Path

MODELS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "yolo11n-pose.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt",
}

folder = Path(__file__).resolve().parents[1] / "models"
folder.mkdir(exist_ok=True)
for name, url in MODELS.items():
    target = folder / name
    if target.exists():
        print(f"{name}: already there")
        continue
    print(f"{name}: downloading...")
    urllib.request.urlretrieve(url, target)
    print(f"{name}: {target.stat().st_size / 1e6:.1f} MB")