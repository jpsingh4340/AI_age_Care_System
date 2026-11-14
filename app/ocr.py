"""Read a photo or PDF of a printed health report and pull out the clinical fields.

OCR reads the text on the page. Plain rules (not the AI model) then find the numbers and fields,
because small AI models misread digits. A nurse still checks every value against the document.
"""
import re
import zlib

from .schemas import OcrLineOut, Reading


class OcrError(Exception):
    """OCR is not ready or could not read the image/PDF. The message is safe to show."""


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


def _extract_pdf_text_fallback(pdf_bytes: bytes) -> list[OcrLineOut]:
    """Fallback PDF text extractor when PyMuPDF is not installed or for simple PDF text streams."""
    chunks: list[str] = []
    # Check both raw and FlateDecode-compressed streams for PDF text operators (...) Tj / TJ
    streams = [pdf_bytes]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL):
        raw_stream = match.group(1)
        streams.append(raw_stream)
        try:
            streams.append(zlib.decompress(raw_stream))
        except Exception:
            pass
    for block in streams:
        for txt_match in re.finditer(rb"\(([^()\\]{2,200})\)\s*Tj", block):
            try:
                decoded = txt_match.group(1).decode("latin-1", errors="ignore").strip()
                if decoded and decoded not in chunks:
                    chunks.append(decoded)
            except Exception:
                pass
    lines: list[OcrLineOut] = []
    for chunk in chunks:
        for raw_line in chunk.splitlines():
            clean = raw_line.strip()
            if clean:
                lines.append(OcrLineOut(text=clean, confidence=0.92))
    return lines


def read_document_lines(file_bytes: bytes, filename: str = "") -> list[OcrLineOut]:
    """Read lines from a PNG, JPG, or PDF document (digital or scanned)."""
    is_pdf = file_bytes.startswith(b"%PDF-") or filename.lower().endswith(".pdf")
    if not is_pdf:
        return read_lines(file_bytes)

    # 1. Try PyMuPDF (pymupdf) for embedded text or scanned page rendering via RapidOCR
    try:
        import pymupdf as fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        lines: list[OcrLineOut] = []
        for page_index in range(min(doc.page_count, 5)):
            page = doc.load_page(page_index)
            text = page.get_text("text").strip()
            if text:
                for raw_line in text.splitlines():
                    clean = raw_line.strip()
                    if clean:
                        lines.append(OcrLineOut(text=clean, confidence=0.95))
            else:
                # Scanned PDF page: render to PNG and run RapidOCR
                pix = page.get_pixmap(dpi=150)
                lines.extend(read_lines(pix.tobytes("png")))
        doc.close()
        if lines:
            return lines
    except ImportError:
        pass
    except Exception:
        pass

    fallback = _extract_pdf_text_fallback(file_bytes)
    if fallback:
        return fallback
    raise OcrError("No readable text was found in this PDF.")


# ---------- finding the numbers ----------
NUMBER = r"(\d{1,3}(?:[.,]\d)?)"

# key, label, unit, words that start the line, pattern for the value
FIELDS = [
    ("report_date", "Report date", "", r"\b(?:report\s*)?date\b(?!\s*of\s*birth)", r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"),
    ("blood_pressure", "Blood pressure", "mmHg", r"blood\s*pressure|\bbp\b", r"(\d{2,3}\s*/\s*\d{2,3})"),
    ("pulse", "Pulse", "bpm", r"\bpulse\b|heart\s*rate", NUMBER),
    ("temperature", "Temperature", "°C", r"\btemp", NUMBER),
    ("spo2", "Oxygen saturation", "%", r"oxygen|spo2|\bsat", NUMBER),
    ("weight", "Weight", "kg", r"\bweight\b", NUMBER),
    ("glucose", "Blood glucose", "mmol/L", r"glucose|\bbsl\b|blood\s*sugar", NUMBER),
]

# Extended metadata and clinical text fields extracted for the Carer-to-Nurse OCR workflow
EXTENDED_TEXT_FIELDS = [
    ("resident_name", "Resident name", "", r"(?:resident|patient)(?:\s*name)?\s*[:\-]", r"([A-Za-z][A-Za-z .'\-]{1,60})"),
    ("dob", "Date of birth", "", r"(?:date\s*of\s*birth|\bdob\b)\s*[:\-]?", r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"),
    ("document_type", "Document type", "", r"(?:document\s*type|report\s*type)\s*[:\-]", r"([A-Za-z][A-Za-z0-9 &/\-]{2,60})"),
    ("medications", "Medication details", "", r"(?:medications?|medicines?|rx)\s*[:\-]", r"(.{2,160})"),
    ("allergies", "Allergy information", "", r"(?:allerg(?:y|ies))\s*[:\-]", r"(.{2,120})"),
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
    elif key in ("report_date", "dob"):
        parts = re.split(r"[/.\-]", value)
        if len(parts) >= 2:
            day, month = int(parts[0]), int(parts[1])
            if not (1 <= day <= 31 and 1 <= month <= 12):
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


def extract_document_fields(lines: list[OcrLineOut]) -> list[dict]:
    """Extract both structured vital readings and clinical document metadata (name, DOB, meds, allergies)."""
    found_map: dict[str, dict] = {}

    # 1. Extract extended text fields (Resident name, DOB, Document type, Medications, Allergies)
    for key, label, unit, label_pattern, value_pattern in EXTENDED_TEXT_FIELDS:
        for line in lines:
            label_match = re.search(label_pattern, line.text, re.IGNORECASE)
            if not label_match:
                continue
            value_match = re.search(value_pattern, line.text[label_match.end():].strip())
            if not value_match:
                continue
            val = value_match.group(1).strip()
            reason = _check(key, val)
            if not reason and line.confidence < LOW_CONFIDENCE:
                reason = "Low OCR confidence on this line. Verify against the original document."
            found_map[key] = {
                "key": key,
                "label": label,
                "value": val,
                "unit": unit,
                "raw_line": line.text,
                "confidence": line.confidence,
                "needs_check": bool(reason),
                "reason": reason,
            }
            break

    # Infer document type from heading if not explicitly labelled
    if "document_type" not in found_map and lines:
        header_text = " ".join(l.text for l in lines[:3]).lower()
        if "discharge" in header_text:
            doc_type = "Hospital Discharge Report"
        elif "lab" in header_text or "pathology" in header_text:
            doc_type = "Laboratory Report"
        elif "medication" in header_text or "chart" in header_text:
            doc_type = "Medication Chart"
        else:
            doc_type = "Health Report"
        found_map["document_type"] = {
            "key": "document_type",
            "label": "Document type",
            "value": doc_type,
            "unit": "",
            "raw_line": lines[0].text,
            "confidence": lines[0].confidence,
            "needs_check": False,
            "reason": "",
        }

    # 2. Extract numeric vital readings using the existing deterministic rules
    for r in extract_readings(lines):
        found_map[r.key] = r.model_dump()

    # Return in a consistent clinical order, including missing key fields as empty editable rows
    ordered_schema = [
        ("resident_name", "Resident name", ""),
        ("dob", "Date of birth", ""),
        ("report_date", "Report date", ""),
        ("document_type", "Document type", ""),
        ("blood_pressure", "Blood pressure", "mmHg"),
        ("pulse", "Pulse", "bpm"),
        ("temperature", "Temperature", "°C"),
        ("spo2", "Oxygen saturation", "%"),
        ("weight", "Weight", "kg"),
        ("glucose", "Blood glucose", "mmol/L"),
        ("medications", "Medication details", ""),
        ("allergies", "Allergy information", ""),
    ]
    result: list[dict] = []
    for key, label, unit in ordered_schema:
        if key in found_map:
            result.append(found_map[key])
        else:
            result.append({
                "key": key,
                "label": label,
                "value": "",
                "unit": unit,
                "raw_line": "",
                "confidence": 0.0,
                "needs_check": key in ("report_date", "blood_pressure", "pulse", "temperature", "spo2"),
                "reason": "Not found on document — fill in if present on the original report." if key in ("report_date", "blood_pressure", "pulse", "temperature", "spo2") else "",
            })
    return result


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
