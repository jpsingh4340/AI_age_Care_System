"""Tests for the fall and stillness rules, using made-up keypoints (no YOLO needed)."""

import numpy as np

from app.vision.fall_monitor import FallConfig, FallDetector, PersonFrame, torso_angle

FPS = 10


def person(t, hip_y, lying=False, jitter=0.0, rng=None):
    """A simple 17-keypoint person. Standing: tall box. Lying: wide box."""
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    if lying:
        bbox = (60, hip_y - 25, 260, hip_y + 25)
        kp[5, :2], kp[6, :2] = (100, hip_y - 5), (100, hip_y + 5)  # shoulders
        kp[11, :2], kp[12, :2] = (170, hip_y - 5), (170, hip_y + 5)  # hips
        kp[:, 0] = np.where(kp[:, 0] == 0, 150, kp[:, 0])
        kp[:, 1] = np.where(kp[:, 1] == 0, hip_y, kp[:, 1])
    else:
        top = hip_y - 120
        bbox = (100, top, 160, top + 200)
        kp[5, :2], kp[6, :2] = (120, hip_y - 70), (140, hip_y - 70)
        kp[11, :2], kp[12, :2] = (122, hip_y), (138, hip_y)
        kp[:, 0] = np.where(kp[:, 0] == 0, 130, kp[:, 0])
        kp[:, 1] = np.where(kp[:, 1] == 0, hip_y, kp[:, 1])
    if jitter and rng is not None:
        kp[:, :2] += rng.normal(0, jitter, size=(17, 2))
    return PersonFrame(t, bbox, kp)


def run(detector, frames):
    events = []
    for f in frames:
        events += detector.update(1, f)
    return events


def fall_sequence():
    frames = [person(i / FPS, 220) for i in range(20)]  # stand 2 s
    for j in range(5):  # fall over 0.5 s
        frames.append(person(2 + j / FPS, 220 + 13 * (j + 1), lying=j >= 3))
    frames += [person(2.5 + i / FPS, 285, lying=True) for i in range(30)]  # lie 3 s
    return frames


def test_torso_angle_upright_and_flat():
    assert torso_angle(person(0, 220).keypoints) < 20
    assert torso_angle(person(0, 285, lying=True).keypoints) > 70


def test_fast_drop_then_lying_is_a_possible_fall():
    events = run(FallDetector(FallConfig(still_seconds=999)), fall_sequence())
    falls = [e for e in events if e.event_type == "possible_fall"]
    assert len(falls) == 1
    assert falls[0].timestamp >= 4.0  # only after lying for the 2 s confirm time
    assert "check" in falls[0].message.lower()


def test_lying_down_slowly_is_not_a_fall():
    frames = [person(i / FPS, 220) for i in range(20)]
    for j in range(50):  # lower over 5 s, e.g. getting into bed
        frames.append(person(2 + j / FPS, 220 + 65 * j / 50, lying=j > 40))
    frames += [person(7 + i / FPS, 285, lying=True) for i in range(30)]
    events = run(FallDetector(FallConfig(still_seconds=999)), frames)
    assert not [e for e in events if e.event_type == "possible_fall"]


def test_one_alert_per_fall_until_person_gets_up():
    det = FallDetector(FallConfig(still_seconds=999))
    frames = fall_sequence() + [person(5.5 + i / FPS, 285, lying=True) for i in range(30)]
    assert len(run(det, frames)) == 1


def test_no_movement_alert_after_still_time():
    det = FallDetector(FallConfig(still_seconds=5))
    events = run(det, [person(i / FPS, 220) for i in range(70)])
    assert [e.event_type for e in events] == ["no_movement"]


def test_moving_person_gets_no_stillness_alert():
    rng = np.random.default_rng(0)
    det = FallDetector(FallConfig(still_seconds=5))
    events = run(det, [person(i / FPS, 220, jitter=4.0, rng=rng) for i in range(70)])
    assert events == []


def test_low_confidence_keypoints_fall_back_to_box_shape():
    f = person(0, 285, lying=True)
    f.keypoints[:, 2] = 0.1
    from app.vision.fall_monitor import is_lying
    assert is_lying(f, FallConfig())