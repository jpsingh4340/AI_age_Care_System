import mediapipe as mp

print("mediapipe version:", getattr(mp, "__version__", "unknown"))
print("has old mp.solutions:", hasattr(mp, "solutions"))

try:
    from mediapipe.tasks.python import vision
    print("has new tasks FaceDetector:", hasattr(vision, "FaceDetector"))
except Exception as error:
    print("tasks import problem:", error)