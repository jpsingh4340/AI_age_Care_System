"""Tests for the cue scoring. They use fixed blendshape numbers, so no camera or model is needed."""

import pytest

from app.vision import cue_check
from app.vision.cue_check import MESSAGES, level_for, pspi_terms, score_blendshapes

NEUTRAL = {"browDownLeft": 0.02, "browDownRight": 0.03, "eyeBlinkLeft": 0.1, "eyeBlinkRight": 0.1}
GRIMACE = {
    "browDownLeft": 0.8, "browDownRight": 0.7,
    "eyeSquintLeft": 0.6, "eyeSquintRight": 0.7,
    "noseSneerLeft": 0.5, "noseSneerRight": 0.4,
    "eyeBlinkLeft": 0.2, "eyeBlinkRight": 0.2,
}


def test_neutral_face_is_low():
    result = score_blendshapes(NEUTRAL)
    assert result.level == "low"
    assert result.message == MESSAGES["low"]


def test_grimace_is_high_and_asks_nurse_to_look_closer():
    result = score_blendshapes(GRIMACE)
    assert result.level == "high"
    assert result.message == "Please look closer at this resident."


def test_pspi_uses_the_larger_of_paired_action_units():
    terms = pspi_terms({"cheekSquintLeft": 0.2, "cheekSquintRight": 0.2, "eyeSquintLeft": 0.6, "eyeSquintRight": 0.6})
    assert terms["eye_narrowing"] == pytest.approx(0.6)


def test_eyes_closed_counts_only_above_threshold():
    assert pspi_terms({"eyeBlinkLeft": 0.4, "eyeBlinkRight": 0.4})["eyes_closed"] == 0.0
    assert pspi_terms({"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9})["eyes_closed"] == 1.0


def test_score_stays_between_zero_and_one():
    everything = {name: 1.0 for name in GRIMACE} | {"mouthUpperUpLeft": 1.0, "mouthUpperUpRight": 1.0}
    assert score_blendshapes(everything).score == 1.0
    assert score_blendshapes({}).score == 0.0


def test_personal_baseline_removes_resting_frown():
    resting_frown = {"browDownLeft": 0.9, "browDownRight": 0.9, "eyeSquintLeft": 0.5, "eyeSquintRight": 0.5}
    baseline = pspi_terms(resting_frown)
    assert score_blendshapes(resting_frown).level != "low"
    assert score_blendshapes(resting_frown, baseline=baseline).level == "low"


@pytest.mark.parametrize("score,level", [(0.0, "low"), (cue_check.LOW_MAX, "medium"),
                                          (cue_check.MEDIUM_MAX, "high"), (1.0, "high")])
def test_band_edges(score, level):
    assert level_for(score) == level


def test_messages_never_name_a_condition():
    banned = ["pain", "disease", "dementia", "stroke", "depress", "diagnos", "medic", "dose", "infection"]
    for text in MESSAGES.values():
        assert not any(word in text.lower() for word in banned), text


def test_result_dict_has_no_image_data():
    body = score_blendshapes(GRIMACE).to_dict()
    assert set(body) == {"status", "level", "score", "cues", "message"}


def test_broad_smile_is_not_flagged():
    """Real blendshapes from a sample portrait of a person smiling widely.
    Before the smile gate this scored 0.57, which is "high"."""
    smiling = {
        "mouthSmileLeft": 0.96, "mouthSmileRight": 0.93,
        "browDownLeft": 0.84, "browDownRight": 0.82,
        "mouthUpperUpLeft": 0.76, "mouthUpperUpRight": 0.76,
        "eyeSquintLeft": 0.74, "eyeSquintRight": 0.66,
        "eyeBlinkLeft": 0.27, "eyeBlinkRight": 0.25,
    }
    assert score_blendshapes(smiling).level == "low"