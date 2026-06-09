import time

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from app.api.auth import (
    MAX_FAILED_LOGINS,
    TOKEN_SALT,
    reset_rate_limits,
    validate_auth_config,
)
from app.api.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CRM_USERNAME", "operator")
    monkeypatch.setenv("CRM_PASSWORD_HASH", generate_password_hash("correct-password"))
    monkeypatch.setenv("CRM_AUTH_SECRET", "auth-test-secret")
    reset_rate_limits()
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient):
    return client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "correct-password"},
    )


def test_login_and_authenticated_request(client):
    login = _login(client)
    assert login.status_code == 200
    assert login.json()["username"] == "operator"

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"username": "operator"}


def test_invalid_credentials_are_generic(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_repeated_failed_logins_are_rate_limited(client):
    for _ in range(MAX_FAILED_LOGINS):
        response = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "correct-password"},
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_protected_api_rejects_missing_invalid_and_expired_tokens(client):
    assert client.get("/api/accounts").status_code == 401
    assert (
        client.get(
            "/api/accounts",
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )

    serializer = URLSafeTimedSerializer(secret_key="auth-test-secret", salt=TOKEN_SALT)
    expired = serializer.dumps(
        {"username": "operator"},
        salt=None,
    )
    original_time = time.time
    try:
        time.time = lambda: original_time() + 8 * 24 * 60 * 60
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {expired}"},
        )
    finally:
        time.time = original_time
    assert response.status_code == 401


def test_health_and_simulation_routes_remain_public(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/simulation/conversation-designs").status_code == 200


def test_missing_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("CRM_USERNAME")
    monkeypatch.delenv("CRM_PASSWORD_HASH")
    monkeypatch.delenv("CRM_AUTH_SECRET")
    with pytest.raises(RuntimeError, match="CRM authentication is not configured"):
        validate_auth_config()
