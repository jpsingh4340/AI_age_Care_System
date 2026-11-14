"""Automated tests for the Carer-to-Nurse Smart OCR Document Workflow (14 test cases)."""
from fastapi.testclient import TestClient

from app import ocr
from app.main import app
from app.schemas import OcrLineOut

client = TestClient(app)

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fake png report bytes"
FAKE_PDF = (
    b"%PDF-1.4\n1 0 obj<<>>endobj\nstream\n"
    b"(Resident name: Margaret T.) Tj\n"
    b"(Date of birth: 12/04/1942) Tj\n"
    b"(Report date: 14/11/2026) Tj\n"
    b"(Blood pressure: 130 / 80 mmHg) Tj\n"
    b"(Pulse: 74 bpm) Tj\n"
    b"(Temperature: 36.7 C) Tj\n"
    b"(Oxygen saturation: 98 %) Tj\n"
    b"(Medications: Paracetamol 500mg) Tj\n"
    b"(Allergies: Penicillin) Tj\n"
    b"endstream\n%%EOF"
)

CARER_HEADERS = {"X-Role": "carer", "X-User": "carer1"}
NURSE_HEADERS = {"X-Role": "nurse", "X-User": "nurse1"}


def _mock_lines(*pairs):
    return [OcrLineOut(text=t, confidence=c) for t, c in pairs]


def test_1_carer_successfully_uploads_document(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(
            ("Resident name: Margaret T.", 0.95),
            ("Report date: 14/11/2026", 0.95),
            ("Pulse: 76 bpm", 0.94),
        ),
    )
    res = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1", "document_type": "Health Report", "carer_comment": "Morning GP report"},
        files={"file": ("report.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["resident_id"] == 1
    assert body["uploaded_by"] == "carer1"
    assert body["review_status"] == "Pending Nurse Review"
    assert body["carer_comment"] == "Morning GP report"


def test_2_ocr_extracts_text_from_image(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(
            ("Resident name: Margaret T.", 0.96),
            ("Date of birth: 12/04/1942", 0.95),
            ("Report date: 14/11/2026", 0.95),
            ("Blood pressure: 128 / 82 mmHg", 0.93),
            ("Pulse: 74 bpm", 0.95),
            ("Temperature: 36.8 C", 0.94),
            ("Oxygen saturation: 97 %", 0.96),
            ("Medications: Amlodipine 5mg OD", 0.91),
            ("Allergies: Penicillin", 0.92),
        ),
    )
    res = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1", "document_type": "Health Report"},
        files={"file": ("vitals.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    )
    assert res.status_code == 201
    fields = {f["key"]: f["value"] for f in res.json()["extracted_fields"]}
    assert fields["blood_pressure"] == "128/82"
    assert fields["pulse"] == "74"
    assert fields["temperature"] == "36.8"
    assert fields["spo2"] == "97"
    assert fields["medications"] == "Amlodipine 5mg OD"
    assert fields["allergies"] == "Penicillin"


def test_3_ocr_processes_scanned_pdf():
    res = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1", "document_type": "Medical Report"},
        files={"file": ("discharge.pdf", FAKE_PDF, "application/pdf")},
        headers=CARER_HEADERS,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["mime_type"] == "application/pdf"
    assert body["review_status"] == "Pending Nurse Review"
    fields = {f["key"]: f["value"] for f in body["extracted_fields"]}
    assert fields["pulse"] == "74"
    assert fields["blood_pressure"] == "130/80"


def test_4_failed_ocr_displays_appropriate_error(monkeypatch):
    def _fail(data, fn=""):
        raise ocr.OcrError("Unreadable scan")

    monkeypatch.setattr(ocr, "read_document_lines", _fail)
    res = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1"},
        files={"file": ("blurry.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["processing_status"] == "OCR Failed"
    assert body["review_status"] == "OCR Failed"
    assert "Unreadable scan" in body["raw_text"]


def test_5_nurse_sees_document_in_pending_queue(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(("Pulse: 78 bpm", 0.95), ("Report date: 14/11/2026", 0.95)),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "2", "document_type": "Health Report"},
        files={"file": ("queue_test.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()

    queue = client.get("/api/ocr/documents?status=Pending%20Nurse%20Review", headers=NURSE_HEADERS)
    assert queue.status_code == 200
    ids = [d["id"] for d in queue.json()]
    assert up["id"] in ids


def test_6_and_7_and_8_nurse_edits_approves_and_carer_sees_approved_status(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(
            ("Report date: 14/11/2026", 0.95),
            ("Pulse: 79 bpm", 0.95),
            ("Blood pressure: 124 / 78 mmHg", 0.95),
        ),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1"},
        files={"file": ("approve_me.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()
    doc_id = up["id"]

    # Nurse approval without verification checkbox must fail (422)
    unverified = client.post(
        f"/api/ocr/documents/{doc_id}/review",
        json={
            "decision": "Approved",
            "verified_accurate": False,
            "fields": [{"key": "pulse", "label": "Pulse", "value": "80", "unit": "bpm"}],
        },
        headers=NURSE_HEADERS,
    )
    assert unverified.status_code == 422

    # Nurse edits pulse from 79 -> 80 and approves with verified_accurate=True
    rev = client.post(
        f"/api/ocr/documents/{doc_id}/review",
        json={
            "decision": "Approved",
            "review_comment": "Checked against original chart.",
            "verified_accurate": True,
            "reviewer_name": "Nurse Sarah",
            "fields": [
                {"key": "report_date", "label": "Report date", "value": "14/11/2026", "unit": ""},
                {"key": "pulse", "label": "Pulse", "value": "80", "unit": "bpm"},
                {"key": "blood_pressure", "label": "Blood pressure", "value": "124/78", "unit": "mmHg"},
            ],
        },
        headers=NURSE_HEADERS,
    )
    assert rev.status_code == 200
    approved_doc = rev.json()
    assert approved_doc["review_status"] == "Approved"
    assert approved_doc["reviewed_by"] == "Nurse Sarah"
    fields_map = {f["key"]: f["value"] for f in approved_doc["extracted_fields"]}
    assert fields_map["pulse"] == "80"

    # Step 8: Carer sees the approved status
    carer_view = client.get(f"/api/ocr/documents/{doc_id}", headers=CARER_HEADERS).json()
    assert carer_view["review_status"] == "Approved"
    assert carer_view["review_comment"] == "Checked against original chart."


def test_9_and_10_nurse_requests_correction_and_carer_resubmits(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(("Pulse: 72 bpm", 0.90)),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1"},
        files={"file": ("needs_fix.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()
    doc_id = up["id"]

    # Step 9: Nurse requests correction
    corr = client.post(
        f"/api/ocr/documents/{doc_id}/review",
        json={
            "decision": "Needs Correction",
            "review_comment": "Bottom half of report is cut off. Please re-upload full page.",
            "verified_accurate": False,
        },
        headers=NURSE_HEADERS,
    )
    assert corr.status_code == 200
    assert corr.json()["review_status"] == "Needs Correction"

    # Step 10: Carer resubmits the document
    resub = client.post(
        f"/api/ocr/documents/{doc_id}/resubmit",
        data={"carer_comment": "Uploaded full page photo."},
        files={"file": ("full_page.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    )
    assert resub.status_code == 200
    assert resub.json()["review_status"] == "Pending Nurse Review"
    assert resub.json()["carer_comment"] == "Uploaded full page photo."


def test_11_carer_cannot_approve_document(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(("Pulse: 70 bpm", 0.95)),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1"},
        files={"file": ("carer_try.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()

    forbidden = client.post(
        f"/api/ocr/documents/{up['id']}/review",
        json={"decision": "Approved", "verified_accurate": True},
        headers=CARER_HEADERS,
    )
    assert forbidden.status_code == 403


def test_12_unauthorised_users_cannot_access_another_residents_documents(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(("Pulse: 70 bpm", 0.95)),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "1"},
        files={"file": ("res1.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()

    # Unauthenticated request -> 401
    assert client.get(f"/api/ocr/documents/{up['id']}").status_code == 401

    # Family role -> 403
    assert client.get(f"/api/ocr/documents/{up['id']}", headers={"X-Role": "family"}).status_code == 403

    # Carer restricted to resident 2 trying to access resident 1's document -> 403
    restricted_carer = {"X-Role": "carer", "X-User": "carer2", "X-Resident-Id": "2"}
    assert client.get(f"/api/ocr/documents/{up['id']}", headers=restricted_carer).status_code == 403
    assert client.get(f"/api/ocr/documents/{up['id']}/file", headers=restricted_carer).status_code == 403


def test_13_and_14_approved_data_persists_and_original_file_remains_available(monkeypatch):
    monkeypatch.setattr(
        ocr,
        "read_document_lines",
        lambda data, fn="": _mock_lines(
            ("Report date: 14/11/2026", 0.96),
            ("Pulse: 84 bpm", 0.96),
        ),
    )
    up = client.post(
        "/api/ocr/documents",
        data={"resident_id": "3"},
        files={"file": ("persist.png", FAKE_PNG, "image/png")},
        headers=CARER_HEADERS,
    ).json()
    doc_id = up["id"]

    client.post(
        f"/api/ocr/documents/{doc_id}/review",
        json={
            "decision": "Approved",
            "review_comment": "Verified.",
            "verified_accurate": True,
            "reviewer_name": "Nurse Sarah",
            "fields": [
                {"key": "report_date", "label": "Report date", "value": "14/11/2026", "unit": ""},
                {"key": "pulse", "label": "Pulse", "value": "84", "unit": "bpm"},
            ],
        },
        headers=NURSE_HEADERS,
    )

    # Step 13: Approved data persists in resident records (Checked Health Report Readings)
    rec = client.get("/api/residents/3/records").json()
    assert any(r["key"] == "pulse" and r["value"] == "84" and r["checked_by"] == "Nurse Sarah" for r in rec["readings_saved"])

    # Step 14: Original medical document remains available for authorised review
    file_res = client.get(f"/api/ocr/documents/{doc_id}/file", headers=NURSE_HEADERS)
    assert file_res.status_code == 200
    assert file_res.content == FAKE_PNG
