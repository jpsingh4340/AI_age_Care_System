import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import auth

client = TestClient(app)


@pytest.fixture(autouse=True)
def init_test_auth(tmp_path, monkeypatch):
    test_db = tmp_path / "test_auth.db"
    monkeypatch.setattr(auth, "DB_PATH", test_db)
    auth.init_auth_db()


def test_seed_users_created():
    nurse = auth.authenticate_user("nurse1", "password123")
    assert nurse is not None
    assert nurse["role"] == "nurse"

    carer = auth.authenticate_user("carer1", "password123")
    assert carer is not None
    assert carer["role"] == "carer"


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

    # Login
    login = client.post("/api/auth/login", json={
        "username": "nurse_jane",
        "password": "securepass123"
    })
    assert login.status_code == 200
    assert login.json()["username"] == "nurse_jane"
    assert login.json()["role"] == "nurse"


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

    # Call /api/auth/me
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

    # Carer token should be rejected on nurse-only endpoint
    r = client.get("/api/guidance/pending", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_nurse_token_accepted_on_nurse_endpoints():
    nurse_login = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "password123"
    }).json()
    token = nurse_login["token"]

    # Nurse token should be accepted
    r = client.get("/api/guidance/pending", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_logout():
    nurse_login = client.post("/api/auth/login", json={
        "username": "nurse1",
        "password": "password123"
    }).json()
    token = nurse_login["token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200

    # Token is now revoked
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
