"""Read a photo of a fake printed health report and pull out the numbers.

OCR reads the text on the page. Plain rules (not the AI model) then find the numbers,
because small AI models misread digits. A nurse still checks every value against the photo.
"""
import re

from .schemas import OcrLineOut, Reading


class OcrError(Exception):
    """OCR is not ready or could not read the image. The message is safe to show."""


# Keep one RapidOCR instance in memory so we only load it once
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # slow to load, so only when first needed
        except ImportError as error:
            raise OcrError(
                "OCR is not installed. Run: pip install rapidocr-onnxruntime python-multipart"
            ) from error
        _engine = RapidOCR()
    return _engine


def group_into_lines(items: list[dict]) -> list[OcrLineOut]:
    """OCR gives separate boxes ("Pulse:" and "76 bpm"). Join boxes on the same row into one line."""
    # Sort all detected text boxes from top to bottom of the page
    items = sorted(items, key=lambda i: (i["top"] + i["bottom"]) / 2)
    rows: list[list[dict]] = []
    for item in items:
        mid = (item["top"] + i_bot) / 2 if (i_bot := item["bottom"]) else (item["top"] + item["bottom"]) / 2
        height = max(item["bottom"] - item["top"], 1)
        if rows:
            last = rows[-1]
            last_mid = sum((i["top"] + i["bottom"]) / 2 for i in last) / len(last)
            # If this box is at almost the same height as the previous box, put it on the same row
            if abs(mid - last_mid) <= max(10, 0.6 * height):
                last.append(item)
                continue
        rows.append([item])

    # Sort each row from left to right and join the words into one line
    lines = []
    for row in rows:
        row.sort(key=lambda i: i["x"])
        text = " ".join(i["text"] for i in row if i["text"])
        score = sum(i["score"] for i in row) / len(row)
        if text:
            lines.append(OcrLineOut(text=text, confidence=round(score, 2)))
    return lines


def read_lines(image_bytes: bytes) -> list[OcrLineOut]:
    # Run RapidOCR on the uploaded image bytes and get bounding boxes + confidence scores
    result, _ = _get_engine()(image_bytes)
    items = []
    for box, text, score in result or []:
        ys = [point[1] for point in box]
        xs = [point[0] for point in box]
        items.append(
            {"text": text.strip(), "score": float(score), "x": min(xs), "top": min(ys), "bottom": max(ys)}
        )
    return group_into_lines(items)


# ---------- finding the numbers ----------
NUMBER = r"(\d{1,3}(?:[.,]\d)?)"

# key, label, unit, words that start the line, pattern for the value
FIELDS = [
    ("report_date", "Report date", "", r"\bdate\b", r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"),
    ("blood_pressure", "Blood pressure", "mmHg", r"blood\s*pressure|\bbp\b", r"(\d{2,3}\s*/\s*\d{2,3})"),
    ("pulse", "Pulse", "bpm", r"\bpulse\b|heart\s*rate", NUMBER),
    ("temperature", "Temperature", "°C", r"\btemp", NUMBER),
    ("spo2", "Oxygen saturation", "%", r"oxygen|spo2|\bsat", NUMBER),
    ("weight", "Weight", "kg", r"\bweight\b", NUMBER),
    ("glucose", "Blood glucose", "mmol/L", r"glucose|\bbsl\b|blood\s*sugar", NUMBER),
]

# Usual ranges. A value outside the range is KEPT (it could be a real concern),
# but it is marked "check the photo" because it may be an OCR mistake.
RANGES = {
    "pulse": (30, 200),
    "temperature": (34, 41.5),
    "spo2": (70, 100),
    "weight": (25, 250),
    "glucose": (2, 35),
}

# Below 70% confidence we warn the nurse to double-check the photo
LOW_CONFIDENCE = 0.7


def _check(key: str, value: str) -> str:
    """Return a reason to double-check this value, or an empty string."""
    # Check if blood pressure, date, or vital sign is outside the normal range
    if key == "blood_pressure":
        top, bottom = [int(part) for part in value.replace(" ", "").split("/")]
        if not (70 <= top <= 230 and 30 <= bottom <= 140 and top > bottom):
            return "This blood pressure looks unusual. Check the photo."
    elif key == "report_date":
        day, month, *_ = re.split(r"[/.\-]", value)
        if not (1 <= int(day) <= 31 and 1 <= int(month) <= 12):
            return "This date does not look right. Check the photo."
    elif key in RANGES:
        low, high = RANGES[key]
        if not (low <= float(value.replace(",", ".")) <= high):
            return "Outside the usual range. Check the photo."
    return ""


def extract_readings(lines: list[OcrLineOut]) -> list[Reading]:
    # Match each health field label in the OCR lines using regex and pull out the number after it
    readings: list[Reading] = []
    for key, label, unit, label_pattern, value_pattern in FIELDS:
        for line in lines:
            label_match = re.search(label_pattern, line.text, re.IGNORECASE)
            if not label_match:
                continue
            value_match = re.search(value_pattern, line.text[label_match.end():])
            if not value_match:
                continue
            value = re.sub(r"\s+", "", value_match.group(1)) if key == "blood_pressure" else value_match.group(1)
            reason = _check(key, value)
            if not reason and line.confidence < LOW_CONFIDENCE:
                reason = "The OCR is not sure about this line. Check the photo."
            readings.append(
                Reading(
                    key=key,
                    label=label,
                    value=value,
                    unit=unit,
                    raw_line=line.text,
                    confidence=line.confidence,
                    needs_check=bool(reason),
                    reason=reason,
                )
            )
            break  # first matching line is enough
    return readings


# ---------- checking values that a nurse saves ----------
FIELD_INFO = {key: (label, unit) for key, label, unit, _, _ in FIELDS}
VALUE_FORMATS = {
    "blood_pressure": r"\d{2,3}/\d{2,3}",
    "report_date": r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}",
}


def value_error(key: str, value: str) -> str:
    """Return a message if the value is not in a valid format, or an empty string.

    Unusual numbers are allowed here (the nurse checked them against the photo and they
    may be real), but a value that is not a number at all is never saved.
    """
    if key not in FIELD_INFO or key == "report_date":
        return f'"{key}" is not a value we can save.'
    pattern = VALUE_FORMATS.get(key, r"\d{1,3}([.,]\d)?")
    if not re.fullmatch(pattern, value.strip()):
        return f'"{value}" is not a valid {FIELD_INFO[key][0].lower()}.'
    return ""
