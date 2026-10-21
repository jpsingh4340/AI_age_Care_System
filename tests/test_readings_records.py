from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
NURSE = {"X-Role": "nurse"}
GOOD = {
    "reviewer": "Nurse Test",
    "report_date": "20/10/2026",
    "readings": [{"key": "pulse", "value": "76"}, {"key": "blood_pressure", "value": "128/82"}],
}


def test_nurse_can_save_and_read_back():
    r = client.post("/api/residents/1/readings", json=GOOD, headers=NURSE)
    assert r.status_code == 200
    assert {x["key"] for x in r.json()} == {"pulse", "blood_pressure"}
    assert r.json()[0]["checked_by"] == "Nurse Test"
    saved = client.get("/api/residents/1/readings").json()
    assert len(saved) == 2
    assert client.get("/api/residents/2/readings").json() == []


def test_carer_cannot_save():
    r = client.post("/api/residents/1/readings", json=GOOD, headers={"X-Role": "carer"})
    assert r.status_code == 403
    assert client.get("/api/residents/1/readings").json() == []


def test_bad_values_are_refused():
    bad = {**GOOD, "readings": [{"key": "pulse", "value": "seventy"}]}
    assert client.post("/api/residents/1/readings", json=bad, headers=NURSE).status_code == 422
    bad = {**GOOD, "readings": [{"key": "colour", "value": "5"}]}
    assert client.post("/api/residents/1/readings", json=bad, headers=NURSE).status_code == 422
    bad = {**GOOD, "report_date": "yesterday"}
    assert client.post("/api/residents/1/readings", json=bad, headers=NURSE).status_code == 422
    dup = {**GOOD, "readings": [{"key": "pulse", "value": "70"}, {"key": "pulse", "value": "71"}]}
    assert client.post("/api/residents/1/readings", json=dup, headers=NURSE).status_code == 422
    assert client.get("/api/residents/1/readings").json() == []


def test_unusual_but_real_number_is_kept():
    odd = {**GOOD, "readings": [{"key": "pulse", "value": "190"}]}
    assert client.post("/api/residents/1/readings", json=odd, headers=NURSE).status_code == 200


def test_unknown_resident():
    assert client.post("/api/residents/99/readings", json=GOOD, headers=NURSE).status_code == 404
    assert client.get("/api/residents/99/readings").status_code == 404
    assert client.get("/api/residents/99/records").status_code == 404


def test_saving_writes_audit_entry():
    client.post("/api/residents/1/readings", json=GOOD, headers=NURSE)
    log = client.get("/api/audit", headers=NURSE).json()
    assert any(e["action"] == "readings_saved" and e["actor"] == "Nurse Test" for e in log)


def test_records_have_everything_the_pdf_needs():
    client.post("/api/residents/1/readings", json=GOOD, headers=NURSE)
    r = client.get("/api/residents/1/records")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Margaret T."
    for field in ("allergies", "doctor", "contacts", "care_plan", "care_record", "concerns"):
        assert data[field], field
    assert {t["status"] for t in data["care_record"]} <= {"given", "refused", "not_done"}
    assert len(data["readings_history"]["pulse"]) == 7
    assert len(data["readings_saved"]) == 2


def test_every_resident_has_records():
    for resident in client.get("/api/residents").json():
        assert client.get(f"/api/residents/{resident['resident_id']}/records").status_code == 200