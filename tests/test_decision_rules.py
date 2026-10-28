"""Tests for the rules layer of the Care Priority Decision feature (Tanveer).

The expected scores come from the NZEWS Adult Vital Signs Chart.
"""
from app.decision_rules import (
    AMBER, BLUE, GREEN, RED, check_vital, check_vitals, highest_level,
    latest_readings, nzews_score, rules_level, total_score,
)


def test_oxygen_bands():
    assert nzews_score("spo2", 97) == 0
    assert nzews_score("spo2", 95) == 1
    assert nzews_score("spo2", 92) == 2
    assert nzews_score("spo2", 91) == 3


def test_heart_rate_bands():
    assert nzews_score("pulse", 84) == 0
    assert nzews_score("pulse", 96) == 1
    assert nzews_score("pulse", 115) == 2
    assert nzews_score("pulse", 45) == 2
    assert nzews_score("pulse", 135) == 3
    assert nzews_score("pulse", 145) == BLUE
    assert nzews_score("pulse", 35) == BLUE


def test_systolic_blood_pressure_bands():
    assert nzews_score("systolic", 136) == 0
    assert nzews_score("systolic", 108) == 1
    assert nzews_score("systolic", 95) == 2
    assert nzews_score("systolic", 80) == 3
    assert nzews_score("systolic", 225) == 3
    assert nzews_score("systolic", 65) == BLUE


def test_temperature_bands():
    assert nzews_score("temperature", 37.1) == 0
    assert nzews_score("temperature", 37.9) == 0
    assert nzews_score("temperature", 38.0) == 1
    assert nzews_score("temperature", 35.5) == 1
    assert nzews_score("temperature", 39.2) == 2
    assert nzews_score("temperature", 34.5) == 2


def test_each_vital_sign_gets_a_level():
    assert check_vital("spo2", 98)["level"] == GREEN
    assert check_vital("spo2", 94)["level"] == AMBER
    assert check_vital("spo2", 90)["level"] == RED
    assert check_vital("pulse", 145)["level"] == RED


def test_reason_is_plain_english_with_the_value():
    result = check_vital("spo2", 93)
    assert result["reason"] == "Oxygen (SpO2) 93 % gives NZEWS score 2."


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
    assert check_vitals(history)[0]["source"] == "Vital signs record, 2026-10-20"


def test_all_normal_is_green():
    results = [check_vital("spo2", 98), check_vital("pulse", 70)]
    assert total_score(results) == 0
    assert rules_level(results) == GREEN


def test_small_total_is_amber():
    # like Joan P.: pulse 96 (1) + systolic 108 (1) + oxygen 93 (2) = 4
    results = [check_vital("pulse", 96), check_vital("systolic", 108), check_vital("spo2", 93)]
    assert total_score(results) == 4
    assert rules_level(results) == AMBER


def test_one_red_zone_vital_sign_is_red():
    results = [check_vital("spo2", 90), check_vital("pulse", 70)]
    assert rules_level(results) == RED


def test_total_of_eight_is_red():
    # 2 + 2 + 2 + 2 = 8, none in the red zone
    results = [check_vital("spo2", 92), check_vital("pulse", 115),
               check_vital("systolic", 95), check_vital("temperature", 39.2)]
    assert total_score(results) == 8
    assert rules_level(results) == RED


def test_highest_level_wins():
    assert highest_level([GREEN, AMBER, GREEN]) == AMBER
    assert highest_level([AMBER, RED]) == RED
    assert highest_level([]) == GREEN