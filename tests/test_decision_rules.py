"""Tests for the rules layer of the Care Priority Decision feature (Tanveer)."""
from app.decision_rules import (
    AMBER, GREEN, RED, check_vital, check_vitals, highest_level, latest_readings,
)


def test_normal_oxygen_is_green():
    assert check_vital("spo2", 98)["level"] == GREEN


def test_low_oxygen_is_amber():
    assert check_vital("spo2", 94)["level"] == AMBER


def test_very_low_oxygen_is_red():
    assert check_vital("spo2", 90)["level"] == RED


def test_high_temperature_is_amber_and_very_high_is_red():
    assert check_vital("temperature", 38.5)["level"] == AMBER
    assert check_vital("temperature", 39.5)["level"] == RED


def test_fast_pulse_is_amber():
    assert check_vital("pulse", 96)["level"] == AMBER


def test_reason_is_plain_english_with_the_value():
    result = check_vital("spo2", 90)
    assert "Oxygen (SpO2) 90 %" in result["reason"]
    assert "very low" in result["reason"]


def test_latest_reading_is_used():
    history = {"pulse": [
        {"date": "2026-10-19", "value": 70},
        {"date": "2026-10-20", "value": 96},
    ]}
    assert latest_readings(history)["pulse"] == {"value": 96, "date": "2026-10-20"}


def test_unknown_vital_signs_are_ignored():
    history = {"diastolic": [{"date": "2026-10-20", "value": 80}]}
    assert check_vitals(history) == []


def test_every_result_shows_its_source():
    history = {"spo2": [{"date": "2026-10-20", "value": 93}]}
    result = check_vitals(history)[0]
    assert result["source"] == "Vital signs record, 2026-10-20"


def test_highest_level_wins():
    assert highest_level([GREEN, AMBER, GREEN]) == AMBER
    assert highest_level([AMBER, RED]) == RED
    assert highest_level([]) == GREEN