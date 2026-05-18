from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.db import repository
from app.db.models import Base


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)

    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setattr("app.api.main.FRONTEND_DIST", frontend_dist)

    with TestClient(app) as test_client:
        yield test_client


def test_account_create_toggle_update_delete_flow(client):
    created = client.post(
        "/api/accounts",
        json={
            "email": "agent@example.com",
            "password": "secret",
            "session_file": "session.json",
            "initial_message": "hello",
            "daily_limit": 9,
            "active": True,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["email"] == "agent@example.com"
    assert payload["persona_type"]

    account_id = payload["id"]

    toggled = client.post(f"/api/accounts/{account_id}/toggle")
    assert toggled.status_code == 200
    assert toggled.json()["active"] is False

    updated = client.patch(
        f"/api/accounts/{account_id}",
        json={"daily_limit": 12, "initial_message": "updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["daily_limit"] == 12
    assert updated.json()["initial_message"] == "updated"

    deleted = client.delete(f"/api/accounts/{account_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_search_profile_crud_and_404s(client):
    account = client.post(
        "/api/accounts",
        json={
            "email": "profiles@example.com",
            "password": "secret",
            "session_file": "session.json",
            "initial_message": "",
            "daily_limit": 8,
            "active": True,
        },
    ).json()

    created = client.post(
        "/api/search-profiles",
        json={
            "account_id": account["id"],
            "location": "Leeds",
            "price_min": 1300,
            "price_max": 2000,
            "bedrooms_min": 1,
            "bedrooms_max": 3,
            "area": 5,
            "pets_allowed": False,
            "active": True,
        },
    )
    assert created.status_code == 200
    profile = created.json()
    assert profile["location"] == "Leeds"
    assert profile["area"] == 5

    updated = client.patch(
        f"/api/search-profiles/{profile['id']}",
        json={
            "account_id": account["id"],
            "location": "Leicester",
            "price_min": 1400,
            "price_max": 2100,
            "bedrooms_min": 2,
            "bedrooms_max": 4,
            "area": 6,
            "pets_allowed": True,
            "active": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["location"] == "Leicester"

    deleted = client.delete(f"/api/search-profiles/{profile['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["active"] is False

    missing_account = client.post("/api/accounts/9999/toggle")
    assert missing_account.status_code == 404

    missing_profile = client.patch(
        "/api/search-profiles/9999",
        json={
            "account_id": account["id"],
            "location": "Nowhere",
            "price_min": 1000,
            "price_max": 1500,
            "bedrooms_min": 1,
            "bedrooms_max": 2,
            "area": 4,
            "pets_allowed": False,
            "active": True,
        },
    )
    assert missing_profile.status_code == 404
