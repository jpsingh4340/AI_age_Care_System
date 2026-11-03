import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import auth
from app.routers import portal

client = TestClient(app)


@pytest.fixture(autouse=True)
def init_test_auth(tmp_path, monkeypatch):
    test_db = tmp_path / "test_auth.db"
    monkeypatch.setattr(auth, "DB_PATH", test_db)
    auth.init_auth_db()


def test_seed_four_role_users_created():
    for username, expected_role in [
        ("carer1", "carer"),
        ("nurse1", "nurse"),
        ("manager1", "manager"),
        ("family1", "family"),
    ]:
        user = auth.authenticate_user(username, "password123")
        assert user is not None
        assert user["role"] == expected_role


def test_register_nurse_and_login():
    reg = client.post("/api/auth/register", json={
        "username": "nurse_jane",
        "password": "securepass123",
        "full_name": "Jane Nurse",
        "role": "nurse"
    })
    assert reg.status_code == 200
    token = reg.json()["token"]
    assert token
    assert reg.json()["role"] == "nurse"

    login = client.post("/api/auth/login", json={
        "username": "nurse_jane",
        "password": "securepass123"
    })
    assert login.status_code == 200
    assert login.json()["username"] == "nurse_jane"
    assert login.json()["role"] == "nurse"


def test_register_family_requires_resident_id():
    missing = client.post("/api/auth/register", json={
        "username": "fam_no_res",
        "password": "password123",
        "full_name": "Sarah Family",
        "role": "family"
    })
    assert missing.status_code == 400

    ok = client.post("/api/auth/register", json={
        "username": "fam_sarah",
        "password": "password123",
        "full_name": "Sarah Family",
        "role": "family",
        "resident_id": 1
    })
    assert ok.status_code == 200
    assert ok.json()["role"] == "family"
    assert ok.json()["resident_id"] == 1


def test_register_duplicate_username_fails():
    client.post("/api/auth/register", json={
        "username": "dup_user",
        "password": "password123",
        "full_name": "First User",
        "role": "carer"
    })
    dup = client.post("/api/auth/register", json={
        "username": "dup_user",
        "password": "password123",
        "full_name": "Second User",
        "role": "carer"
    })
    assert dup.status_code == 400
    assert "already taken" in dup.json()["detail"]


def test_login_invalid_credentials():
    r = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "wrongpassword"
    })
    assert r.status_code == 401


def test_auth_me_endpoint():
    login = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "password123"
    }).json()
    token = login["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "nurse1"
    assert me.json()["role"] == "nurse"


def test_carer_token_rejected_on_nurse_endpoints():
    carer_login = client.post("/api/auth/login", json={
        "username": "carer1",
        "password": "password123"
    }).json()
    token = carer_login["token"]

    r = client.get("/api/guidance/pending", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_nurse_token_accepted_on_nurse_endpoints():
    nurse_login = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "password123"
    }).json()
    token = nurse_login["token"]

    r = client.get("/api/guidance/pending", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_nurse_approves_family_update_and_family_reads_it(monkeypatch):
    # Force fast rule fallback so test does not wait on Ollama
    monkeypatch.setattr(portal, "draft_family_text", lambda person, rec: ("Kia ora, Margaret had a good day.", "Rules"))

    nurse_token = client.post("/api/auth/login", json={"username": "nurse1", "password": "password123"}).json()["token"]
    fam_token = client.post("/api/auth/login", json={"username": "family1", "password": "password123"}).json()["token"]

    # Family cannot draft updates
    forbidden = client.post(
        "/api/family-updates/draft",
        json={"resident_id": 1},
        headers={"Authorization": f"Bearer {fam_token}"},
    )
    assert forbidden.status_code == 403

    # Nurse drafts and approves update for resident 1
    draft = client.post(
        "/api/family-updates/draft",
        json={"resident_id": 1},
        headers={"Authorization": f"Bearer {nurse_token}"},
    )
    assert draft.status_code == 200
    upd_id = draft.json()["id"]

    # Before approval, family sees 0 approved updates
    fam_before = client.get("/api/family/me", headers={"Authorization": f"Bearer {fam_token}"}).json()
    assert fam_before["updates"] == []

    # Nurse approves & sends
    sent = client.post(
        f"/api/family-updates/{upd_id}/send",
        json={"text": "Kia ora, Margaret had a calm, happy day today."},
        headers={"Authorization": f"Bearer {nurse_token}"},
    )
    assert sent.status_code == 200

    # Family now sees the approved update
    fam_after = client.get("/api/family/me", headers={"Authorization": f"Bearer {fam_token}"}).json()
    assert len(fam_after["updates"]) == 1
    assert "calm, happy day" in fam_after["updates"][0]["text"]


def test_manager_overview_and_user_management():
    mgr_token = client.post("/api/auth/login", json={"username": "manager1", "password": "password123"}).json()["token"]
    carer_token = client.post("/api/auth/login", json={"username": "carer1", "password": "password123"}).json()["token"]

    # Carer cannot access manager overview
    assert client.get("/api/manager/overview", headers={"Authorization": f"Bearer {carer_token}"}).status_code == 403

    # Manager can access overview and create a user
    ov = client.get("/api/manager/overview", headers={"Authorization": f"Bearer {mgr_token}"})
    assert ov.status_code == 200
    assert len(ov.json()["kpis"]) >= 4

    created = client.post(
        "/api/manager/users",
        json={
            "username": "carer_new",
            "password": "password123",
            "full_name": "New Carer",
            "role": "carer",
        },
        headers={"Authorization": f"Bearer {mgr_token}"},
    )
    assert created.status_code == 201


def test_logout():
    nurse_login = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "password123"
    }).json()
    token = nurse_login["token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
