from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
import os
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash


TOKEN_SALT = "land-royal-crm"
TOKEN_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_FAILED_LOGINS = 5
AUTH_ERROR = "Authentication required"
INVALID_CREDENTIALS_ERROR = "Invalid username or password"

_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_failed_logins_lock = Lock()


def get_auth_config() -> tuple[str, str, str]:
    return (
        os.getenv("CRM_USERNAME", "").strip(),
        os.getenv("CRM_PASSWORD_HASH", "").strip(),
        os.getenv("CRM_AUTH_SECRET", "").strip(),
    )


def validate_auth_config() -> None:
    username, password_hash, secret = get_auth_config()
    missing = [
        name
        for name, value in (
            ("CRM_USERNAME", username),
            ("CRM_PASSWORD_HASH", password_hash),
            ("CRM_AUTH_SECRET", secret),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"CRM authentication is not configured. Missing: {', '.join(missing)}"
        )


def _serializer() -> URLSafeTimedSerializer:
    _, _, secret = get_auth_config()
    if not secret:
        raise RuntimeError("CRM_AUTH_SECRET is not configured")
    return URLSafeTimedSerializer(secret_key=secret, salt=TOKEN_SALT)


def issue_token(username: str) -> str:
    return _serializer().dumps(
        {
            "username": username,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def verify_token(token: str) -> str:
    try:
        payload = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=401, detail=AUTH_ERROR) from exc

    username, _, _ = get_auth_config()
    if not isinstance(payload, dict) or payload.get("username") != username:
        raise HTTPException(status_code=401, detail=AUTH_ERROR)
    return username


def verify_request(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail=AUTH_ERROR)
    return verify_token(token)


def _prune_failed_logins(ip_address: str, now: float) -> deque[float]:
    failures = _failed_logins[ip_address]
    cutoff = now - LOGIN_WINDOW_SECONDS
    while failures and failures[0] <= cutoff:
        failures.popleft()
    return failures


def ensure_login_allowed(ip_address: str) -> None:
    now = time.monotonic()
    with _failed_logins_lock:
        failures = _prune_failed_logins(ip_address, now)
        if len(failures) >= MAX_FAILED_LOGINS:
            retry_after = max(1, int(LOGIN_WINDOW_SECONDS - (now - failures[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )


def record_failed_login(ip_address: str) -> None:
    now = time.monotonic()
    with _failed_logins_lock:
        _prune_failed_logins(ip_address, now).append(now)


def clear_failed_logins(ip_address: str) -> None:
    with _failed_logins_lock:
        _failed_logins.pop(ip_address, None)


def authenticate(username: str, password: str) -> bool:
    configured_username, password_hash, _ = get_auth_config()
    return username == configured_username and check_password_hash(password_hash, password)


def reset_rate_limits() -> None:
    with _failed_logins_lock:
        _failed_logins.clear()
