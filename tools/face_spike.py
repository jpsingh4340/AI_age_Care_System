"""Spike: can MediaPipe find a face on this laptop?
Own photo only. This script never saves, copies or shows the image.
It does NOT judge emotion, health or disease. It only counts faces."""
import sys
import time

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL = r"C:\Studio5-private\blaze_face_short_range.tflite"

if len(sys.argv) != 2:
    sys.exit("Use: python tools/face_spike.py C:\\Studio5-private\\me.jpg")

image = cv2.imread(sys.argv[1])
if image is None:
    sys.exit("Could not open that image. Check the path.")

rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
height, width = rgb.shape[:2]

options = vision.FaceDetectorOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    min_detection_confidence=0.5,
)
detector = vision.FaceDetector.create_from_options(options)
mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

started = time.perf_counter()
result = detector.detect(mp_image)
first = time.perf_counter() - started

# run 5 more times to get a fair average speed
started = time.perf_counter()
for _ in range(5):
    detector.detect(mp_image)
average = (time.perf_counter() - started) / 5

faces = result.detections
print(f"Image size: {width} x {height}")
print(f"Faces found: {len(faces)}")
for number, face in enumerate(faces, start=1):
    print(f"  Face {number}: confidence {face.categories[0].score:.2f}")
print(f"First run: {first:.3f} seconds")
print(f"Average of 5 more runs: {average:.3f} seconds")