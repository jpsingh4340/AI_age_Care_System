"""OCR tests. They run WITHOUT the real OCR engine, using made-up OCR output."""
from fastapi.testclient import TestClient

from app import ocr
from app.main import app
from app.schemas import OcrLineOut

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes"


def box(text, x, top, score=0.9, height=30):
    return {"text": text, "x": x, "top": top, "bottom": top + height, "score": score}


def test_boxes_on_the_same_row_are_joined_in_order():
    items = [
        box("76 bpm", 418, 357),
        box("Pulse:", 37, 354),
        box("Temperature:", 39, 422),
        box("36.8 C", 419, 420),
    ]
    lines = ocr.group_into_lines(items)
    assert [line.text for line in lines] == ["Pulse: 76 bpm", "Temperature: 36.8 C"]


def lines(*pairs):
    return [OcrLineOut(text=text, confidence=score) for text, score in pairs]


def test_numbers_are_found_with_their_units():
    found = ocr.extract_readings(
        lines(
            ("Date: 18/10/2026", 0.9),
            ("Blood pressure: 128 / 82 mmHg", 0.9),
            ("Pulse: 76 bpm", 0.9),
            ("Temperature: 36.8 C", 0.9),
            ("Oxygen saturation: 96 %", 0.9),
            ("Weight: 71.5 kg", 0.9),
            ("Blood glucose: 6,1 mmol/L", 0.9),
        )
    )
    values = {r.key: r.value for r in found}
    assert values == {
        "report_date": "18/10/2026",
        "blood_pressure": "128/82",
        "pulse": "76",
        "temperature": "36.8",
        "spo2": "96",
        "weight": "71.5",
        "glucose": "6,1",
    }
    assert not any(r.needs_check for r in found)


def test_unusual_or_unsure_values_are_kept_but_marked_for_checking():
    found = {
        r.key: r
        for r in ocr.extract_readings(
            lines(
                ("Pulse: 276 bpm", 0.9),  # outside the usual range
                ("Temperature: 36.8 C", 0.4),  # OCR not sure
                ("Blood pressure: 40/90", 0.9),  # top number lower than bottom
            )
        )
    }
    assert found["pulse"].value == "276" and found["pulse"].needs_check
    assert found["temperature"].needs_check and "not sure" in found["temperature"].reason
    assert found["blood_pressure"].needs_check


def test_nothing_is_invented_when_the_page_has_no_numbers():
    assert ocr.extract_readings(lines(("Hello world", 0.9), ("Pulse: unreadable", 0.9))) == []


def test_api_reads_an_image(monkeypatch):
    monkeypatch.setattr(ocr, "read_lines", lambda data: lines(("Pulse: 76 bpm", 0.9)))
    response = TestClient(app).post("/api/ocr/extract", files={"file": ("r.png", PNG, "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["readings"][0]["value"] == "76"
    assert "nurse must check" in body["status_note"]


def test_api_rejects_files_that_are_not_images_or_too_big(monkeypatch):
    client = TestClient(app)
    bad = client.post("/api/ocr/extract", files={"file": ("a.txt", b"hello", "text/plain")})
    assert bad.status_code == 400
    big = client.post("/api/ocr/extract", files={"file": ("big.png", PNG + b"0" * (7 * 1024 * 1024), "image/png")})
    assert big.status_code == 413


def test_api_says_so_when_ocr_is_not_installed(monkeypatch):
    def not_installed(data):
        raise ocr.OcrError("OCR is not installed.")

    monkeypatch.setattr(ocr, "read_lines", not_installed)
    response = TestClient(app).post("/api/ocr/extract", files={"file": ("r.png", PNG, "image/png")})
    assert response.status_code == 503
    