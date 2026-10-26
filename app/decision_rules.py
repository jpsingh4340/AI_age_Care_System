"""Rules layer for the Care Priority Decision feature (written by Tanveer).

This file checks a resident's vital signs with fixed numbers (thresholds).
There is NO AI in this file, so the same numbers always give the same result,
and every result can be explained.

Each vital sign gets a level:
    Green = inside the normal range
    Amber = a nurse should check
    Red   = a nurse should see the resident now

IMPORTANT: the numbers in THRESHOLDS below are PROTOTYPE values for testing only.
They will be replaced with the bands from the New Zealand Early Warning Score
(NZEWS) vital signs chart (Health Quality & Safety Commission). This is a student
prototype, not a clinical tool, and all residents are fake.
"""

GREEN = "Green"
AMBER = "Amber"
RED = "Red"

# Lets us compare levels: Red is the highest.
LEVEL_RANK = {GREEN: 0, AMBER: 1, RED: 2}

# For each vital sign:
#   red_low    -> value at or below this is Red
#   amber_low  -> value at or below this is Amber
#   amber_high -> value at or above this is Amber
#   red_high   -> value at or above this is Red
# None means "no limit on this side".
THRESHOLDS = {
    "spo2": {
        "label": "Oxygen (SpO2)", "unit": "%",
        "red_low": 91, "amber_low": 95, "amber_high": None, "red_high": None,
    },
    "temperature": {
        "label": "Temperature", "unit": "°C",
        "red_low": 35.0, "amber_low": 36.0, "amber_high": 38.1, "red_high": 39.1,
    },
    "pulse": {
        "label": "Pulse", "unit": "bpm",
        "red_low": 40, "amber_low": 50, "amber_high": 91, "red_high": 131,
    },
    "systolic": {
        "label": "Systolic blood pressure", "unit": "mmHg",
        "red_low": 90, "amber_low": 100, "amber_high": 180, "red_high": 220,
    },
}


def check_vital(key: str, value: float) -> dict:
    """Check one vital sign and return its level and a plain-English reason."""
    rule = THRESHOLDS[key]
    label, unit = rule["label"], rule["unit"]

    if rule["red_low"] is not None and value <= rule["red_low"]:
        level, why = RED, f"is very low (at or below {rule['red_low']} {unit})"
    elif rule["red_high"] is not None and value >= rule["red_high"]:
        level, why = RED, f"is very high (at or above {rule['red_high']} {unit})"
    elif rule["amber_low"] is not None and value <= rule["amber_low"]:
        level, why = AMBER, f"is low (at or below {rule['amber_low']} {unit})"
    elif rule["amber_high"] is not None and value >= rule["amber_high"]:
        level, why = AMBER, f"is high (at or above {rule['amber_high']} {unit})"
    else:
        level, why = GREEN, "is in the normal range"

    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "level": level,
        "reason": f"{label} {value} {unit} {why}.",
    }


def latest_readings(readings_history: dict) -> dict:
    """From the readings history, keep only the newest value of each vital sign.

    readings_history looks like {"pulse": [{"date": "2026-10-20", "value": 84}, ...], ...}
    Returns {"pulse": {"value": 84, "date": "2026-10-20"}, ...}
    """
    latest = {}
    for key, entries in readings_history.items():
        if key in THRESHOLDS and entries:
            newest = max(entries, key=lambda entry: entry["date"])
            latest[key] = {"value": newest["value"], "date": newest["date"]}
    return latest


def check_vitals(readings_history: dict) -> list[dict]:
    """Check the newest value of every vital sign we have rules for.

    Each result also keeps the date of the reading, so the nurse can see the source.
    """
    results = []
    for key, reading in latest_readings(readings_history).items():
        result = check_vital(key, reading["value"])
        result["source"] = f"Vital signs record, {reading['date']}"
        results.append(result)
    return results


def highest_level(levels: list[str]) -> str:
    """Return the most serious level in the list. An empty list gives Green."""
    if not levels:
        return GREEN
    return max(levels, key=lambda level: LEVEL_RANK[level])