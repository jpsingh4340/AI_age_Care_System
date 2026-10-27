"""Rules layer for the Care Priority Decision feature (written by Tanveer).

This file checks a resident's vital signs with the New Zealand Early Warning
Score (NZEWS) bands from the Adult Vital Signs Chart (Te Tāhū Hauora Health
Quality & Safety Commission). There is NO AI in this file, so the same numbers
always give the same result, and every result can be explained.

How it works:
1. Each vital sign gets an NZEWS score of 0, 1, 2 or 3, or the blue zone
   (blue = immediately life threatening on the chart).
2. The scores are added up to give a total.
3. The total and the zones give one level for the resident:
       Red   = any vital sign in the red zone (score 3) or blue zone, or total 8 or more
       Amber = total 1 to 7
       Green = total 0

Limits: our records only have 4 of the 7 NZEWS vital signs (no respiratory rate,
supplemental oxygen or level of consciousness), so this is a guide for a student
prototype, not a clinical tool. All residents are fake.
"""

GREEN = "Green"
AMBER = "Amber"
RED = "Red"
BLUE = "blue"  # blue zone on the NZEWS chart

# Lets us compare levels: Red is the highest.
LEVEL_RANK = {GREEN: 0, AMBER: 1, RED: 2}

# NZEWS bands. Each band is (start value, score). A value gets the score of the
# last band whose start is at or below the value. The first band starts at
# minus infinity so every value has a band.
LOWEST = float("-inf")
NZEWS_BANDS = {
    "spo2": {
        "label": "Oxygen (SpO2)", "unit": "%",
        "bands": [(LOWEST, 3), (92, 2), (94, 1), (96, 0)],
    },
    "pulse": {
        "label": "Heart rate", "unit": "bpm",
        "bands": [(LOWEST, BLUE), (40, 2), (50, 0), (90, 1), (110, 2), (130, 3), (140, BLUE)],
    },
    "systolic": {
        "label": "Systolic blood pressure", "unit": "mmHg",
        "bands": [(LOWEST, BLUE), (70, 3), (90, 2), (100, 1), (110, 0), (220, 3)],
    },
    "temperature": {
        "label": "Temperature", "unit": "°C",
        "bands": [(LOWEST, 2), (35.0, 1), (36.0, 0), (38.0, 1), (39.0, 2)],
    },
}


def nzews_score(key: str, value: float):
    """Return the NZEWS score (0 to 3) or BLUE for one vital sign value."""
    score = None
    for start, band_score in NZEWS_BANDS[key]["bands"]:
        if value >= start:
            score = band_score
    return score


def _level_for_score(score) -> str:
    """Red for the red or blue zone, Amber for score 1 or 2, Green for 0."""
    if score == BLUE or score == 3:
        return RED
    if score in (1, 2):
        return AMBER
    return GREEN


def check_vital(key: str, value: float) -> dict:
    """Check one vital sign and return its NZEWS score, level and a plain-English reason."""
    info = NZEWS_BANDS[key]
    label, unit = info["label"], info["unit"]
    score = nzews_score(key, value)

    if score == BLUE:
        why = "is in the NZEWS blue zone (immediately life threatening)"
    elif score == 0:
        why = "is in the normal range (NZEWS score 0)"
    else:
        why = f"gives NZEWS score {score}"

    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "score": score,
        "level": _level_for_score(score),
        "reason": f"{label} {value} {unit} {why}.",
    }


def latest_readings(readings_history: dict) -> dict:
    """From the readings history, keep only the newest value of each vital sign.

    readings_history looks like {"pulse": [{"date": "2026-10-20", "value": 84}, ...], ...}
    Returns {"pulse": {"value": 84, "date": "2026-10-20"}, ...}
    """
    latest = {}
    for key, entries in readings_history.items():
        if key in NZEWS_BANDS and entries:
            newest = max(entries, key=lambda entry: entry["date"])
            latest[key] = {"value": newest["value"], "date": newest["date"]}
    return latest


def check_vitals(readings_history: dict) -> list[dict]:
    """Check the newest value of every vital sign we have NZEWS bands for.

    Each result also keeps the date of the reading, so the nurse can see the source.
    """
    results = []
    for key, reading in latest_readings(readings_history).items():
        result = check_vital(key, reading["value"])
        result["source"] = f"Vital signs record, {reading['date']}"
        results.append(result)
    return results


def total_score(results: list[dict]) -> int:
    """Add up the NZEWS scores. A blue zone counts as 3 in the total."""
    return sum(3 if r["score"] == BLUE else r["score"] for r in results)


def rules_level(results: list[dict]) -> str:
    """One level for the resident from their vital signs, following the NZEWS chart."""
    if any(r["level"] == RED for r in results):
        return RED  # any vital sign in the red or blue zone
    total = total_score(results)
    if total >= 8:
        return RED
    if total >= 1:
        return AMBER
    return GREEN


def highest_level(levels: list[str]) -> str:
    """Return the most serious level in the list. An empty list gives Green."""
    if not levels:
        return GREEN
    return max(levels, key=lambda level: LEVEL_RANK[level])