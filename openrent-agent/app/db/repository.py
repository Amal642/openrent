from contextlib import contextmanager
import random
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import joinedload

from app.db.connection import SessionLocal
from app.db.models import (
    Account,
    Conversation,
    Landlord,
    LeadSheetExport,
    Listing,
    Message,
    SearchProfile,
)
from app.db.status import HANDOFF_COMPLETE, VIEWING_CANCELLED, VIEWING_BOOKED, VIEWING_DISCUSSION
from app.utils.scheduling import uk_now
from app.ai.personas import (
    get_conversation_style,
    get_persona_template,
    materialize_persona,
    normalize_conversation_style,
    select_persona,
)


def _utc(dt: datetime | None) -> datetime | None:
    """Attach UTC timezone to a naive datetime so API clients parse it correctly."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------- PROXIES ----------------

PROXY_TYPES = {"static", "rotating"}


def _normalize_proxy_type(proxy_type) -> str:
    proxy_type = (proxy_type or "static").strip().lower()
    return proxy_type if proxy_type in PROXY_TYPES else "static"


def _next_proxy_name(db, proxy_type="static") -> str:
    from app.db.models import Proxy as _Proxy
    proxy_type = _normalize_proxy_type(proxy_type)
    count = db.query(_Proxy).filter(_Proxy.proxy_type == proxy_type).count()
    label = "Static Proxy" if proxy_type == "static" else "Rotating Proxy"
    return f"{label} {count + 1}"


def create_proxy(name=None, host="", port=0, username=None, password=None, is_active=True, proxy_type="static"):
    from app.db.models import Proxy as _Proxy
    proxy_type = _normalize_proxy_type(proxy_type)
    with session_scope() as db:
        proxy = _Proxy(
            name=name or _next_proxy_name(db, proxy_type),
            host=host,
            port=port,
            username=username or None,
            password=password or None,
            is_active=is_active,
            proxy_type=proxy_type,
        )
        db.add(proxy)
        db.commit()
        db.refresh(proxy)
        return {
            "id": proxy.id,
            "name": proxy.name,
            "host": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "is_active": proxy.is_active,
            "proxy_type": proxy.proxy_type,
            "created_at": proxy.created_at,
            "account_count": 0,
        }


def get_proxies():
    from app.db.models import Proxy as _Proxy
    with session_scope() as db:
        proxies = db.query(_Proxy).order_by(_Proxy.id.asc()).all()
        return [_serialize_proxy(p, db) for p in proxies]


def get_proxy(proxy_id: int):
    from app.db.models import Proxy as _Proxy
    with session_scope() as db:
        p = db.query(_Proxy).filter(_Proxy.id == proxy_id).first()
        if not p:
            return None
        return _serialize_proxy(p, db)


def _serialize_proxy(proxy, db) -> dict:
    from app.db.models import Account as _Account
    count = db.query(_Account).filter(_Account.proxy_id == proxy.id).count()
    return {
        "id": proxy.id,
        "name": proxy.name,
        "host": proxy.host,
        "port": proxy.port,
        "username": proxy.username,
        "is_active": proxy.is_active,
        "proxy_type": proxy.proxy_type or "static",
        "created_at": proxy.created_at,
        "updated_at": proxy.updated_at,
        "account_count": count,
    }


def update_proxy(proxy_id: int, **kwargs):
    from app.db.models import Proxy as _Proxy
    if "proxy_type" in kwargs and kwargs["proxy_type"] is not None:
        kwargs["proxy_type"] = _normalize_proxy_type(kwargs["proxy_type"])
    # The real password is never sent back to the frontend (security), so the
    # edit dialog always submits password="" unless the user retypes it. An
    # empty string here means "leave unchanged", not "clear the password" —
    # only a non-empty value should overwrite what's stored.
    if kwargs.get("password") == "":
        kwargs.pop("password", None)
    with session_scope() as db:
        p = db.query(_Proxy).filter(_Proxy.id == proxy_id).first()
        if not p:
            return None
        allowed = {"name", "host", "port", "username", "password", "is_active", "proxy_type"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(p, key, value)
        p.updated_at = datetime.utcnow()
        db.commit()
        return _serialize_proxy(p, db)


def delete_proxy(proxy_id: int):
    from app.db.models import Proxy as _Proxy, Account as _Account
    with session_scope() as db:
        p = db.query(_Proxy).filter(_Proxy.id == proxy_id).first()
        if not p:
            return None, "not_found"
        in_use = db.query(_Account).filter(_Account.proxy_id == proxy_id).count()
        if in_use:
            return None, f"in_use:{in_use}"
        db.delete(p)
        db.commit()
        return {"deleted": True, "id": proxy_id}, None


def find_replacement_proxy(exclude_proxy_id: int, prefer_type: str = "static"):
    """
    Pick a healthy, active, spare proxy to take over for a failing one.
    Prefers prefer_type (e.g. keep static accounts on static proxies),
    falling back to any healthy active proxy of another type. Among
    candidates of the preferred type, picks the least-loaded one (fewest
    accounts already assigned) to spread load. Returns the proxy id, or
    None if nothing suitable is available.
    """
    from sqlalchemy import or_
    from app.db.models import Proxy as _Proxy, Account as _Account

    prefer_type = _normalize_proxy_type(prefer_type)

    with session_scope() as db:
        candidates = (
            db.query(_Proxy)
            .filter(
                _Proxy.id != exclude_proxy_id,
                _Proxy.is_active == True,
                or_(_Proxy.health_status == "ok", _Proxy.health_status == None),
            )
            .all()
        )
        if not candidates:
            return None

        def _load(proxy_id: int) -> int:
            return db.query(_Account).filter(_Account.proxy_id == proxy_id).count()

        preferred = [c for c in candidates if _normalize_proxy_type(c.proxy_type) == prefer_type]
        pool = preferred if preferred else candidates
        pool.sort(key=lambda c: _load(c.id))
        return pool[0].id


def reassign_account_proxy(account_id: int, reason: str = "proxy_failure"):
    """
    Move an account off its current (repeatedly failing) proxy onto a
    healthy replacement, preferring the same proxy type. Deactivates the
    old proxy so it isn't handed out to other accounts while still broken.
    If no replacement is available, marks the account failed so the
    problem is visible on the dashboard instead of retrying forever.
    """
    from app.db.models import Account as _Account, Proxy as _Proxy
    from app.utils.logger import logger

    with session_scope() as db:
        account = db.query(_Account).filter(_Account.id == account_id).first()
        if not account or not account.proxy_id:
            return {"reassigned": False, "reason": "no_proxy_assigned"}
        old_proxy_id = account.proxy_id
        old_proxy = db.query(_Proxy).filter(_Proxy.id == old_proxy_id).first()
        prefer_type = _normalize_proxy_type(old_proxy.proxy_type if old_proxy else "static")

    new_proxy_id = find_replacement_proxy(old_proxy_id, prefer_type=prefer_type)

    if not new_proxy_id:
        mark_account_failed(
            account_id,
            f"NO_SPARE_PROXY_AVAILABLE old_proxy_id={old_proxy_id} reason={reason}",
        )
        logger.error(
            f"PROXY_REASSIGN_FAILED account_id={account_id} "
            f"old_proxy_id={old_proxy_id} reason=no_spare_available"
        )
        return {"reassigned": False, "reason": "no_spare_available", "old_proxy_id": old_proxy_id}

    with session_scope() as db:
        account = db.query(_Account).filter(_Account.id == account_id).first()
        if not account:
            return {"reassigned": False, "reason": "account_missing"}
        account.proxy_id = new_proxy_id
        account.proxy_status = "unknown"
        account.proxy_failures = 0

        old_proxy = db.query(_Proxy).filter(_Proxy.id == old_proxy_id).first()
        if old_proxy:
            old_proxy.is_active = False
            old_proxy.updated_at = datetime.utcnow()

        db.commit()

    logger.warning(
        f"PROXY_REASSIGNED account_id={account_id} "
        f"old_proxy_id={old_proxy_id} new_proxy_id={new_proxy_id} reason={reason}"
    )
    return {"reassigned": True, "old_proxy_id": old_proxy_id, "new_proxy_id": new_proxy_id}


def proxy_account_count(proxy_id: int) -> int:
    with session_scope() as db:
        from app.db.models import Account as _Account
        return db.query(_Account).filter(_Account.proxy_id == proxy_id).count()


# ---------------- ACCOUNTS ----------------

def create_account(
    email,
    password,
    session_file,
    initial_message,
    proxy_server=None,
    proxy_username=None,
    proxy_password=None,
    mobile_number=None,
    persona_type=None,
    phone_fetching_type=None,
    message_strategy=None,
    escalation_behavior=None,
    conversation_goal=None,
    conversation_style=None,
):
    with session_scope() as db:
        account = Account(
            email=email,
            password=password,
            session_file=session_file,
            initial_message=initial_message,
            proxy_server=proxy_server,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
            mobile_number=mobile_number,
            persona_type=persona_type,
            phone_fetching_type=phone_fetching_type,
            message_strategy=message_strategy,
            escalation_behavior=escalation_behavior,
            conversation_goal=conversation_goal,
            conversation_style=conversation_style,
        )

        db.add(account)
        db.commit()
        db.refresh(account)

        return account


def update_account(
    account_id,
    email=None,
    password=None,
    session_file=None,
    initial_message=None,
    proxy_id=None,
    proxy_server=None,
    proxy_username=None,
    proxy_password=None,
    daily_limit=None,
    active=None,
    persona_type=None,
    mobile_number=None,
    phone_fetching_type=None,
    message_strategy=None,
    escalation_behavior=None,
    conversation_goal=None,
    conversation_style=None,
):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        if email is not None:
            account.email = email
        if password is not None:
            account.password = password
        if session_file is not None:
            account.session_file = session_file
        if initial_message is not None:
            account.initial_message = initial_message
        if proxy_id is not None:
            account.proxy_id = proxy_id
        if proxy_server is not None:
            account.proxy_server = proxy_server
        if proxy_username is not None:
            account.proxy_username = proxy_username
        if proxy_password is not None:
            account.proxy_password = proxy_password
        if daily_limit is not None:
            account.daily_limit = daily_limit
        if active is not None:
            account.active = active
        if persona_type is not None:
            account.persona_type = persona_type
        if mobile_number is not None:
            account.mobile_number = mobile_number
        if phone_fetching_type is not None:
            account.phone_fetching_type = phone_fetching_type
        if message_strategy is not None:
            account.message_strategy = message_strategy
        if escalation_behavior is not None:
            account.escalation_behavior = escalation_behavior
        if conversation_goal is not None:
            account.conversation_goal = conversation_goal
        if conversation_style is not None:
            account.conversation_style = normalize_conversation_style(conversation_style)

        db.commit()

    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        return serialize_account(account) if account else None


def get_account(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        return serialize_account(account) if account else None


def _parse_generated_names(names_text):
    names = {}

    if isinstance(names_text, dict):
        return names_text

    for line in str(names_text or "").splitlines():
        match = re.match(r"\s*(husband|wife)\s*:\s*(.+?)\s*$", line, re.I)
        if match:
            names[match.group(1).lower()] = match.group(2).strip()

    words = re.findall(r"[A-Za-z][A-Za-z'-]+", str(names_text or ""))
    if "husband" not in names and words:
        names["husband"] = words[0]
    if "wife" not in names and len(words) > 1:
        names["wife"] = words[1]

    return names


def ensure_account_persona(account_or_id):
    account_id = getattr(account_or_id, "id", account_or_id)

    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        template = get_persona_template(account.persona_type) if account.persona_type else None
        partner_required = bool(template and template["names"]["partner"])
        missing = any(
            getattr(account, field) in (None, "")
            for field in (
                "persona_type",
                "persona_name",
                "persona_job",
                "home_city",
                "phone_fetching_type",
                "message_strategy",
                "escalation_behavior",
                "conversation_goal",
                "conversation_style",
            )
        )
        if partner_required:
            missing = missing or any(
                getattr(account, field) in (None, "")
                for field in (
                    "persona_partner_name",
                    "persona_partner_job",
                )
            )

        if missing:
            used_names = set()
            for row in db.query(Account.persona_name, Account.persona_partner_name).filter(
                Account.id != account_id
            ).all():
                if row[0]:
                    used_names.add(row[0])
                if row[1]:
                    used_names.add(row[1])

            selected = (
                materialize_persona(template, seed=f"{account.id}:{account.email}", exclude_names=used_names)
                if template
                else materialize_persona(
                    get_persona_template(select_persona()["persona_type"]),
                    seed=f"{account.id}:{account.email}",
                    exclude_names=used_names,
                )
            )
            account.persona_type = account.persona_type or selected["persona_type"]
            account.persona_name = account.persona_name or selected["persona_name"]
            account.persona_partner_name = (
                account.persona_partner_name or selected["persona_partner_name"]
            )
            account.persona_job = account.persona_job or selected["persona_job"]
            account.persona_partner_job = (
                account.persona_partner_job or selected["persona_partner_job"]
            )
            account.home_city = account.home_city or selected.get("home_city")
            account.conversation_style = (
                account.conversation_style or selected["conversation_style"]
            )
            style_config = get_conversation_style(account.conversation_style)
            account.phone_fetching_type = (
                account.phone_fetching_type
                or selected.get("phone_fetching_type")
                or style_config["phone_fetching_type"]
            )
            account.message_strategy = (
                account.message_strategy
                or selected.get("message_strategy")
                or style_config["strategy"]
            )
            account.escalation_behavior = (
                account.escalation_behavior
                or selected.get("escalation_behavior")
                or style_config["escalation_behavior"]
            )
            account.conversation_goal = (
                account.conversation_goal
                or selected.get("conversation_goal")
                or style_config["conversation_goal"]
            )
            db.commit()

        template = get_persona_template(account.persona_type) or {}
        conversation_style = normalize_conversation_style(
            account.conversation_style
            or (template.get("conversation_styles") or ["friendly_viewing"])[0]
        )
        style_config = get_conversation_style(conversation_style)

        return {
            "persona_type": account.persona_type,
            "persona_name": account.persona_name,
            "persona_partner_name": account.persona_partner_name,
            "persona_job": account.persona_job,
            "persona_partner_job": account.persona_partner_job,
            "home_city": account.home_city,
            "household_description": template.get("household_description"),
            "message_tone": template.get("message_tone"),
            "display_name": template.get("display_name"),
            "mobile_number": account.mobile_number,
            "phone_fetching_type": (
                account.phone_fetching_type
                or template.get("phone_fetching_type")
                or style_config["phone_fetching_type"]
            ),
            "message_strategy": (
                account.message_strategy
                or template.get("message_strategy")
                or style_config["strategy"]
            ),
            "escalation_behavior": (
                account.escalation_behavior
                or template.get("escalation_behavior")
                or style_config["escalation_behavior"]
            ),
            "conversation_goal": (
                account.conversation_goal
                or template.get("conversation_goal")
                or style_config["conversation_goal"]
            ),
            "conversation_style": conversation_style,
            "conversation_styles": template.get("conversation_styles") or [],
            "screening_posture": template.get("screening_posture"),
            "phone_boundary": template.get("phone_boundary"),
        }


def serialize_account(account):
    persona = ensure_account_persona(account.id)
    next_run_at = None
    if account.cooldown_until and account.cooldown_until > datetime.utcnow():
        next_run_at = account.cooldown_until

    return {
        "id": account.id,
        "email": account.email,
        "session_file": account.session_file,
        "proxy_id": account.proxy_id,
        "proxy_name": account.proxy.name if account.proxy else None,
        "proxy_server": account.proxy_server,
        "proxy_username": account.proxy_username,
        "proxy_password": account.proxy_password,
        "initial_message": account.initial_message,
        "daily_limit": account.daily_limit,
        "messages_sent_today": account.messages_sent_today,
        "messages_sent_reset_at": _utc(account.messages_sent_reset_at),
        "active": account.active,
        "created_at": _utc(account.created_at),
        "persona_name": persona["persona_name"] if persona else None,
        "persona_partner_name": persona["persona_partner_name"] if persona else None,
        "persona_job": persona["persona_job"] if persona else None,
        "persona_partner_job": persona["persona_partner_job"] if persona else None,
        "persona_type": persona["persona_type"] if persona else None,
        "household_description": persona["household_description"] if persona else None,
        "message_tone": persona["message_tone"] if persona else None,
        "persona_label": persona["display_name"] if persona else None,
        "mobile_number": persona["mobile_number"] if persona else None,
        "phone_fetching_type": persona["phone_fetching_type"] if persona else None,
        "message_strategy": persona["message_strategy"] if persona else None,
        "escalation_behavior": persona["escalation_behavior"] if persona else None,
        "conversation_goal": persona["conversation_goal"] if persona else None,
        "conversation_style": persona["conversation_style"] if persona else None,
        "conversation_styles": persona["conversation_styles"] if persona else [],
        "screening_posture": persona.get("screening_posture") if persona else None,
        "phone_boundary": persona.get("phone_boundary") if persona else None,
        "worker_status": account.worker_status or "idle",
        "worker_job_id": account.worker_job_id,
        "worker_started_at": _utc(account.worker_started_at),
        "worker_last_heartbeat": _utc(account.worker_last_heartbeat),
        "worker_error": account.worker_error,
        "worker_last_error": account.worker_last_error,
        "worker_last_completed_at": _utc(account.worker_last_completed_at),
        "last_run_at": _utc(account.worker_last_completed_at),
        "current_worker_phase": account.current_worker_phase or "idle",
        "cooldown_until": _utc(account.cooldown_until),
        "next_run_at": _utc(next_run_at),
        "last_login_at": _utc(account.last_login_at),
        "session_status": account.session_status or "expired",
        "session_last_checked": _utc(account.session_last_checked),
        "session_last_error": account.session_last_error,
        "session_auth_failures": account.session_auth_failures or 0,
        "session_captcha_triggers": account.session_captcha_triggers or 0,
        "proxy_status": account.proxy_status or "unknown",
        "proxy_ip": account.proxy_ip,
        "proxy_latency": account.proxy_latency,
        "proxy_last_checked": _utc(account.proxy_last_checked),
        "proxy_last_error": account.proxy_last_error,
        "proxy_failures": account.proxy_failures or 0,
        "retry_count": account.retry_count or 0,
        "retry_limit": account.retry_limit or 3,
        "retry_reason": account.retry_reason,
        "retry_next_at": _utc(account.retry_next_at),
        "last_exception": account.last_exception,
        "permanently_failed": bool(account.permanently_failed),
        "failed": bool(account.failed) if hasattr(account, "failed") else False,
        "failed_at": _utc(account.failed_at) if hasattr(account, "failed_at") else None,
        "failure_reason": account.failure_reason if hasattr(account, "failure_reason") else None,
    }


def get_active_accounts():
    with session_scope() as db:
        accounts = (
            db.query(Account)
            .options(joinedload(Account.proxy))
            .filter(Account.active == True)
            .all()
        )
        for account in accounts:
            ensure_account_persona(account.id)
        return accounts


def get_dashboard_accounts():
    with session_scope() as db:
        accounts = (
            db.query(Account)
            .options(joinedload(Account.proxy))
            .order_by(Account.created_at.desc())
            .all()
        )
        return [serialize_account(account) for account in accounts]


def get_capacity_stats():
    from app.db.models import Proxy as _Proxy

    in_flight_statuses = {"running", "queued", "stopping", "retrying"}
    with session_scope() as db:
        all_accounts = db.query(Account).all()
        all_proxies = db.query(_Proxy).filter(_Proxy.is_active == True).all()

        running = sum(1 for a in all_accounts if (a.worker_status or "").lower() == "running")
        queued = sum(1 for a in all_accounts if (a.worker_status or "").lower() == "queued")
        in_flight = sum(
            1 for a in all_accounts
            if (a.worker_status or "").lower() in in_flight_statuses
        )
        healthy_proxies = sum(
            1 for p in all_proxies
            if (p.health_status or "").lower() in {"ok", "healthy"}
        )
        failed_proxies = sum(
            1 for p in all_proxies
            if (p.health_status or "").lower() in {"down", "failed"}
        )
        return {
            "accounts_running": running,
            "accounts_queued": queued,
            "accounts_in_flight": in_flight,
            "healthy_proxies": healthy_proxies,
            "failed_proxies": failed_proxies,
            "total_proxies": len(all_proxies),
        }


def update_account_worker_state(
    account_id,
    status,
    phase=None,
    error=None,
    job_id=None,
    retry_reason=None,
    retry_next_at=None,
):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return

        account.worker_status = status
        account.worker_last_heartbeat = datetime.utcnow()
        account.current_worker_phase = phase or account.current_worker_phase
        account.worker_last_error = error
        account.worker_error = error
        if job_id is not None:
            account.worker_job_id = job_id
        if status == "running" and not account.worker_started_at:
            account.worker_started_at = datetime.utcnow()
        if status in ("completed", "idle") and phase == "completed":
            account.worker_last_completed_at = datetime.utcnow()
            account.worker_started_at = None
            account.retry_count = 0
            account.retry_reason = None
            account.retry_next_at = None
            account.last_exception = None
            account.permanently_failed = False
        if status in ("error", "proxy_error", "login_error"):
            account.last_exception = error
        if status == "retrying":
            account.retry_count = (account.retry_count or 0) + 1
            account.retry_reason = retry_reason or error
            account.retry_next_at = retry_next_at
        if status in ("running", "idle"):
            account.last_login_at = account.last_login_at or datetime.utcnow()
        db.commit()


def update_proxy_health(account_id, result):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        healthy = bool(result.get("healthy"))
        latency = result.get("latency")
        account.proxy_status = result.get("status") if result.get("status") == "not_configured" else (
            "ok" if healthy else "down"
        )
        if latency is not None and healthy and latency > 5:
            account.proxy_status = "degraded"
        account.proxy_ip = result.get("ip") or account.proxy_ip
        account.proxy_latency = latency
        account.proxy_last_checked = datetime.utcnow()
        account.proxy_last_error = result.get("error")
        if not healthy:
            account.proxy_failures = (account.proxy_failures or 0) + 1
        else:
            account.proxy_failures = 0
        if account.proxy:
            account.proxy.health_status = "ok" if healthy else "down"
            account.proxy.last_check_at = account.proxy_last_checked
            account.proxy.failure_count = (
                0 if healthy else (account.proxy.failure_count or 0) + 1
            )
        db.commit()
        db.refresh(account)
        return serialize_account(account)


def update_session_health(
    account_id,
    status,
    error=None,
    captcha_triggered=False,
    login_success=False,
    cooldown_minutes=None,
):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        account.session_status = status
        account.session_last_checked = datetime.utcnow()
        account.session_last_error = error
        if login_success:
            account.last_login_at = datetime.utcnow()
            account.session_auth_failures = 0
            account.cooldown_until = None
        elif status in ("error", "expired", "login_failed"):
            account.session_auth_failures = (account.session_auth_failures or 0) + 1
        if captcha_triggered:
            account.session_captcha_triggers = (
                account.session_captcha_triggers or 0
            ) + 1
        if cooldown_minutes is not None:
            account.cooldown_until = datetime.utcnow() + timedelta(minutes=cooldown_minutes)
        db.commit()
        db.refresh(account)
        return serialize_account(account)


def account_stop_requested(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return True

        return account.active is False or account.worker_status == "stopping"


# ---------------- SEARCH PROFILES ----------------

def create_search_profile(
    account_id,
    location,
    price_min,
    price_max,
    bedrooms_min,
    bedrooms_max,
    area,
    pets_allowed=False
):
    with session_scope() as db:
        profile = SearchProfile(
            account_id=account_id,
            location=location,
            price_min=price_min,
            price_max=price_max,
            bedrooms_min=bedrooms_min,
            bedrooms_max=bedrooms_max,
            area=area,
            pets_allowed=pets_allowed
        )

        db.add(profile)
        db.commit()
        db.refresh(profile)

        return profile


def delete_account(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return False

        profiles = (
            db.query(SearchProfile)
            .filter(SearchProfile.account_id == account_id)
            .all()
        )

        for profile in profiles:
            listings = (
                db.query(Listing)
                .filter(Listing.search_profile_id == profile.id)
                .all()
            )
            for listing in listings:
                conversations = (
                    db.query(Conversation)
                    .filter(Conversation.listing_id == listing.id)
                    .all()
                )
                for conversation in conversations:
                    (
                        db.query(Message)
                        .filter(Message.conversation_id == conversation.id)
                        .delete(synchronize_session=False)
                    )
                    db.delete(conversation)
                db.delete(listing)
            db.delete(profile)

        db.delete(account)
        db.commit()
        return True


def get_search_profiles(account_id):
    with session_scope() as db:
        return db.query(SearchProfile).filter(
            SearchProfile.account_id == account_id,
            SearchProfile.active == True
        ).all()


def has_scraped_today(account_id):
    """Legacy helper — use should_scrape_now() for new code."""
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.listings_last_scraped_at:
            return False
        return account.listings_last_scraped_at.date() == uk_now().date()


def should_scrape_now(account_id, cooldown_hours=2):
    """
    Returns True if a scrape should run for this account.
    Scrapes run when listings_last_scraped_at is NULL (never scraped)
    or older than cooldown_hours, whichever comes first.
    Using a time-based cooldown instead of a calendar-day gate avoids
    locking out an account for a full day if the first stamp was premature
    (e.g., the account had no search profiles at the time).
    """
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.listings_last_scraped_at:
            return True
        cutoff = datetime.utcnow() - timedelta(hours=cooldown_hours)
        return account.listings_last_scraped_at < cutoff


def mark_scraped_today(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account:
            account.listings_last_scraped_at = datetime.utcnow()
            db.commit()


def count_available_inventory(account_id: int) -> int:
    stale_before = datetime.utcnow() - timedelta(minutes=30)
    with session_scope() as db:
        return (
            db.query(Listing)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                SearchProfile.account_id == account_id,
                Listing.message_sent == False,
                Listing.processing_failed == False,
                Listing.skip_reason == None,
                Listing.listing_archived == False,
                (
                    (Listing.processing_owner == None)
                    | (Listing.processing_started_at < stale_before)
                ),
            )
            .count()
        )


def count_discovered_today(account_id: int) -> int:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as db:
        return (
            db.query(Listing)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                SearchProfile.account_id == account_id,
                Listing.first_seen >= today_start,
            )
            .count()
        )


# ---------------- ACCOUNT COOLDOWNS ----------------

def set_account_cooldown(account_id: int) -> None:
    """
    Apply a random 20–40 minute cooldown after an account worker completes.
    Prevents the same account from running on every scheduler tick.
    """
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account:
            minutes = random.randint(20, 40)
            account.cooldown_until = datetime.utcnow() + timedelta(minutes=minutes)
            db.commit()
            from app.utils.logger import logger
            logger.info(
                "Account cooling down until: "
                f"{account.cooldown_until.strftime('%Y-%m-%d %H:%M')}"
            )


# ---------------- OUTREACH PACING ----------------
# Separate from the account worker cooldown above: this gates only NEW
# initial-message sending so outreach spreads across the whole operating
# day, while reply-checking keeps running on the fast 20-40 min cooldown.

OUTREACH_GAP_MIN_HOURS = 1
OUTREACH_GAP_MAX_HOURS = 3


def set_next_outreach_at(account_id: int) -> None:
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account:
            hours = random.uniform(OUTREACH_GAP_MIN_HOURS, OUTREACH_GAP_MAX_HOURS)
            account.next_outreach_at = datetime.utcnow() + timedelta(hours=hours)
            db.commit()
            from app.utils.logger import logger
            logger.info(
                f"NEXT_OUTREACH_SCHEDULED account_id={account_id} "
                f"next_outreach_at={account.next_outreach_at.strftime('%Y-%m-%d %H:%M')}"
            )


def is_outreach_due(account_id: int) -> bool:
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.next_outreach_at:
            return True
        return datetime.utcnow() >= account.next_outreach_at


def is_account_on_cooldown(account_id: int) -> bool:
    from app.utils.scheduling import UK_TZ
    from app.utils.logger import logger as _logger

    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.cooldown_until:
            return False

        now_utc = datetime.utcnow()
        cooldown_utc = account.cooldown_until
        still_on_cooldown = cooldown_utc > now_utc

        cooldown_uk = cooldown_utc.replace(tzinfo=timezone.utc).astimezone(UK_TZ)
        now_uk = now_utc.replace(tzinfo=timezone.utc).astimezone(UK_TZ)

        _logger.info(
            f"ACCOUNT_COOLDOWN_DEBUG account_id={account_id} "
            f"cooldown_until_raw={cooldown_utc} "
            f"cooldown_until_timezone=UTC "
            f"cooldown_until_uk={cooldown_uk.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"current_time_raw={now_utc} "
            f"current_time_timezone=UTC "
            f"current_time_uk={now_uk.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"comparison_result={cooldown_utc}>{now_utc}=={still_on_cooldown} "
            f"cooldown_expired={not still_on_cooldown}"
        )

        return still_on_cooldown


# ---------------- LISTINGS ----------------

def listing_exists(listing_id):
    with session_scope() as db:
        exists = db.query(Listing).filter(
            Listing.listing_id == listing_id
        ).first()

        return exists is not None


def create_listing(
    listing_id,
    property_url,
    search_profile_id
):
    with session_scope() as db:
        listing = Listing(
            listing_id=listing_id,
            property_url=property_url,
            search_profile_id=search_profile_id
        )

        db.add(listing)
        db.commit()
        db.refresh(listing)

        return listing


def get_uncontacted_listings(
    account_id,
    limit=5
):
    with session_scope() as db:
        return (
            db.query(Listing)
            .join(
                SearchProfile,
                Listing.search_profile_id == SearchProfile.id
            )
            .filter(
                SearchProfile.account_id == account_id,
                Listing.message_sent == False,
                Listing.processing_failed == False,
                Listing.skip_reason == None,
            )
            .limit(limit)
            .all()
        )


def claim_uncontacted_listings(account_id, worker_id, limit=5, stale_minutes=30):
    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)

    with session_scope() as db:
        listings = (
            db.query(Listing)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                SearchProfile.account_id == account_id,
                Listing.message_sent == False,
                Listing.processing_failed == False,
                Listing.skip_reason == None,
                Listing.listing_archived == False,
                (
                    (Listing.processing_owner == None)
                    | (Listing.processing_started_at < stale_before)
                ),
            )
            .limit(limit)
            .all()
        )

        for listing in listings:
            listing.processing_owner = worker_id
            listing.processing_started_at = datetime.utcnow()

        db.commit()
        return listings


def release_listing_claim(listing_id, worker_id=None):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing:
            return
        if worker_id and listing.processing_owner not in (None, worker_id):
            return
        listing.processing_owner = None
        listing.processing_started_at = None
        db.commit()


def mark_listing_contacted(
    listing_id,
    thread_id=None
):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.contacted = True
            listing.message_sent = True
            listing.thread_id = thread_id
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None

            db.commit()


def mark_listing_failed(listing_id):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.processing_failed = True
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None

            db.commit()

def save_message_url(
    listing_id,
    message_url
):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.message_url = message_url
            db.commit()


def save_listing_metadata(listing_id, metadata):
    from app.utils.logger import logger

    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing:
            logger.warning(
                f"LISTING_METADATA_SAVE_SKIPPED listing_pk={listing_id} reason=not_found"
            )
            return False

        listing.property_address = metadata.get("address") or listing.property_address
        listing.bedrooms = (
            metadata.get("bedrooms")
            if metadata.get("bedrooms") is not None
            else listing.bedrooms
        )
        listing.bathrooms = (
            metadata.get("bathrooms")
            if metadata.get("bathrooms") is not None
            else listing.bathrooms
        )
        listing.rent_pcm = (
            metadata.get("rent_pcm")
            if metadata.get("rent_pcm") is not None
            else listing.rent_pcm
        )
        listing.landlord_name = (
            metadata.get("landlord_name") or listing.landlord_name
        )
        listing.metadata_captured_at = datetime.utcnow()
        db.commit()
        logger.info(
            "LISTING_METADATA_SAVED "
            f"listing_pk={listing.id} listing_id={listing.listing_id} "
            f"address_present={bool(listing.property_address)} "
            f"landlord_name_present={bool(listing.landlord_name)} "
            f"bedrooms={listing.bedrooms} bathrooms={listing.bathrooms} "
            f"rent_pcm={listing.rent_pcm}"
        )
        return True


def can_send_message(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(
            Account.id == account_id
        ).first()

        if not account:
            return False

        today = uk_now().date()
        if not account.messages_sent_reset_at or account.messages_sent_reset_at.date() != today:
            account.messages_sent_today = 0
            account.messages_sent_reset_at = datetime.utcnow()
            db.commit()

        return account.messages_sent_today < account.daily_limit


def increment_message_count(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(
            Account.id == account_id
        ).first()

        if account:
            today = uk_now().date()
            if not account.messages_sent_reset_at or account.messages_sent_reset_at.date() != today:
                account.messages_sent_today = 0
                account.messages_sent_reset_at = datetime.utcnow()
            account.messages_sent_today += 1
            db.commit()


def create_conversation(
    thread_id,
    listing_id=None,
    conversation_style=None,
    landlord_attitude=None,
):
    with session_scope() as db:
        conversation = Conversation(
            thread_id=thread_id,
            listing_id=listing_id,
            conversation_stage="NEW_LEAD",
            conversation_style=normalize_conversation_style(conversation_style)
            if conversation_style else None,
            landlord_attitude=landlord_attitude or "responsive",
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        return conversation


def get_or_create_conversation(thread_id, listing_id=None, conversation_style=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            return conversation

        conversation = Conversation(
            thread_id=thread_id,
            listing_id=listing_id,
            conversation_stage="NEW_LEAD",
            conversation_style=normalize_conversation_style(conversation_style)
            if conversation_style else None,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation


def claim_conversation(thread_id, worker_id, stale_minutes=20):
    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        if (
            conversation.processing_owner
            and conversation.processing_owner != worker_id
            and conversation.processing_started_at
            and conversation.processing_started_at >= stale_before
        ):
            db.rollback()
            return False

        conversation.processing_owner = worker_id
        conversation.processing_started_at = datetime.utcnow()
        db.commit()
        return True


def release_conversation_claim(thread_id, worker_id=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()
        if not conversation:
            return
        if worker_id and conversation.processing_owner not in (None, worker_id):
            return
        conversation.processing_owner = None
        conversation.processing_started_at = None
        db.commit()


def save_message(thread_id, direction, content, created_at=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        message = Message(
            conversation_id=conversation.id,
            direction=direction,
            content=content,
            created_at=created_at or datetime.utcnow(),
        )
        conversation.last_message_at = message.created_at
        if direction == "outbound":
            conversation.last_outbound_at = message.created_at
        db.add(message)
        db.commit()


def save_message_once(thread_id, direction, content, created_at=None):
    content = (content or "").strip()
    if not content:
        return

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        existing = db.query(Message).filter(
            Message.conversation_id == conversation.id,
            Message.direction == direction,
            Message.content == content,
        ).first()

        if existing:
            return

        message = Message(
            conversation_id=conversation.id,
            direction=direction,
            content=content,
            created_at=created_at or datetime.utcnow(),
        )
        conversation.last_message_at = message.created_at
        if direction == "outbound":
            conversation.last_outbound_at = message.created_at
        db.add(message)
        db.commit()


def save_inbound_messages(thread_id, messages):
    for message in messages or []:
        if message.get("sender") != "landlord":
            continue
        save_message_once(
            thread_id,
            "inbound",
            message.get("message") or message.get("content") or "",
        )

def save_viewing_datetime(thread_id, viewing_datetime):
    from app.utils.logger import logger

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.viewing_datetime = viewing_datetime
            conversation.viewing_confirmed = True
            conversation.conversation_stage = "VIEWING_BOOKED"
            conversation.last_stage_change = datetime.utcnow()

            # Randomize when to send the cancellation so the timing varies
            # naturally between conversations (3.2–4.8 hours before viewing).
            if not conversation.cancel_target_hours:
                cancel_target = round(random.uniform(3.2, 4.8), 1)
                conversation.cancel_target_hours = cancel_target
                logger.info(
                    f"Viewing booked for thread {thread_id}. "
                    f"Cancellation target: {cancel_target}h before viewing."
                )

            db.commit()

_STAGE_RANK = {
    "NEW_LEAD": 0,
    "NEW_REPLY": 1,
    "VIEWING_DISCUSSION": 2,
    "VIEWING_PENDING": 2,
    "PRE_VIEWING": 2,
    "CONTACT_REQUESTED": 3,
    "VIEWING_BOOKED": 4,
    "PHONE_ACQUIRED": 5,
    "HANDOFF_COMPLETE": 6,
    "VIEWING_CANCELLED": 7,
}


def save_banner_state(
    thread_id,
    *,
    viewing_requested: bool = False,
    viewing_confirmed: bool = False,
    viewing_datetime=None,
):
    """
    Persist deterministic viewing state extracted from OpenRent system banners.
    Stage is only advanced, never downgraded.
    """
    from app.utils.logger import logger

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            return

        now = datetime.utcnow()
        current_rank = _STAGE_RANK.get(conversation.conversation_stage or "", 0)

        if viewing_requested and not conversation.viewing_requested:
            conversation.viewing_requested = True
            if current_rank < _STAGE_RANK[VIEWING_BOOKED]:
                conversation.conversation_stage = VIEWING_DISCUSSION
                conversation.last_stage_change = now
                logger.info(
                    f"VIEWING_REQUESTED_DETECTED thread_id={thread_id} "
                    "stage=VIEWING_DISCUSSION"
                )

        if viewing_confirmed:
            conversation.viewing_confirmed = True
            if viewing_datetime:
                conversation.viewing_datetime = viewing_datetime
                if not conversation.cancel_target_hours:
                    cancel_target = round(random.uniform(3.2, 4.8), 1)
                    conversation.cancel_target_hours = cancel_target
            if conversation.conversation_stage not in (
                "HANDOFF_COMPLETE",
                "VIEWING_CANCELLED",
            ):
                conversation.conversation_stage = VIEWING_BOOKED
                conversation.last_stage_change = now
            logger.info(
                f"VIEWING_CONFIRMED_BANNER_DETECTED thread_id={thread_id} "
                f"datetime={viewing_datetime} stage=VIEWING_BOOKED"
            )

        db.commit()


def mark_viewing_cancelled(
    thread_id
):

    with session_scope() as db:

        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:

            conversation.viewing_cancelled = True
            conversation.cancellation_sent_at = datetime.utcnow()

            conversation.conversation_stage = (
                VIEWING_CANCELLED
            )

            conversation.last_stage_change = (
                datetime.utcnow()
            )

            db.commit()

def mark_phone_requested(
    thread_id
):

    with session_scope() as db:

        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:

            conversation.phone_requested_at = (
                datetime.utcnow()
            )

            conversation.conversation_stage = (
                "CONTACT_REQUESTED"
            )
            conversation.last_stage_change = datetime.utcnow()

            db.commit()


def mark_phone_number_shared(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.phone_number_shared_at = datetime.utcnow()
            db.commit()


def mark_landlord_asked_phone(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.landlord_asked_phone_at = datetime.utcnow()
            db.commit()


def update_conversation_memory(
    thread_id,
    *,
    landlord_attitude=None,
    conversation_style=None,
):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            if landlord_attitude:
                conversation.landlord_attitude = landlord_attitude
            if conversation_style:
                conversation.conversation_style = normalize_conversation_style(
                    conversation_style
                )
            db.commit()


def update_conversation_stage(thread_id, stage):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            if conversation.conversation_stage != stage:
                conversation.conversation_stage = stage
                conversation.last_stage_change = datetime.utcnow()
            db.commit()


def mark_handoff_complete(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            now = datetime.utcnow()
            conversation.conversation_stage = HANDOFF_COMPLETE
            conversation.handoff_completed_at = now
            conversation.last_stage_change = now
            db.commit()


# ---------------- FOLLOW-UP / INACTIVITY (cold leads with zero landlord reply) ----------------

def increment_follow_up_count(thread_id) -> int:
    """Increment follow_up_count and return the new value."""
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()
        if not conversation:
            return 0
        conversation.follow_up_count = (conversation.follow_up_count or 0) + 1
        db.commit()
        return conversation.follow_up_count


def reset_follow_up_count(thread_id) -> None:
    """Reset follow_up_count to 0 — called when the landlord finally replies,
    so a conversation reactivated from INACTIVE_NO_REPLY gets a fresh cadence
    if it ever goes silent again."""
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()
        if conversation and conversation.follow_up_count:
            conversation.follow_up_count = 0
            db.commit()


def mark_conversation_inactive(thread_id) -> None:
    """Mark a cold lead inactive after the follow-up cadence is exhausted.
    Does not touch conversation_stage — if the landlord replies later,
    the normal reply flow picks the thread back up automatically."""
    from app.db.status import INACTIVE_NO_REPLY
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()
        if conversation:
            conversation.status = INACTIVE_NO_REPLY
            db.commit()


def update_conversation_status(
    thread_id,
    status
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.status = status
            db.commit()


def save_conversation_error(thread_id, reason):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.ai_error_reason = reason
            db.commit()


def save_phone_number(
    thread_id,
    phone
):
    from app.utils.logger import logger

    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            now = datetime.utcnow()
            conversation.extracted_phone = phone
            conversation.phone_found = True
            conversation.phone_found_at = now
            conversation.status = "PHONE_ACQUIRED"

            export = db.query(LeadSheetExport).filter(
                LeadSheetExport.conversation_id == conversation.id
            ).first()
            if not export:
                export = LeadSheetExport(
                    conversation_id=conversation.id,
                    status="PENDING",
                    next_attempt_at=now,
                )
                db.add(export)
                export_action = "created"
            else:
                export.status = "PENDING"
                export.next_attempt_at = now
                export.processing_started_at = None
                export.last_error = None
                export.exported_at = None
                export.updated_at = now
                export_action = "reset"
            db.commit()
            logger.info(
                "GOOGLE_SHEETS_OUTBOX_UPSERTED "
                f"conversation_id={conversation.id} thread_id={thread_id} "
                f"export_id={export.id} action={export_action} status={export.status}"
            )


def claim_due_sheet_exports(limit=20, stale_minutes=15, max_attempts=8):
    now = datetime.utcnow()
    stale_before = now - timedelta(minutes=stale_minutes)

    with session_scope() as db:
        exports = (
            db.query(LeadSheetExport)
            .filter(
                LeadSheetExport.attempt_count < max_attempts,
                (
                    (
                        LeadSheetExport.status.in_(("PENDING", "FAILED"))
                        & (
                            (LeadSheetExport.next_attempt_at == None)
                            | (LeadSheetExport.next_attempt_at <= now)
                        )
                    )
                    | (
                        (LeadSheetExport.status == "PROCESSING")
                        & (LeadSheetExport.processing_started_at < stale_before)
                    )
                ),
            )
            .order_by(LeadSheetExport.created_at.asc())
            .limit(limit)
            .all()
        )

        claimed_ids = []
        for export in exports:
            export.status = "PROCESSING"
            export.processing_started_at = now
            export.updated_at = now
            claimed_ids.append(export.id)
        db.commit()
        return claimed_ids


def get_sheet_export_payload(export_id):
    with session_scope() as db:
        row = (
            db.query(
                LeadSheetExport,
                Conversation,
                Listing,
                SearchProfile,
                Account,
            )
            .join(
                Conversation,
                LeadSheetExport.conversation_id == Conversation.id,
            )
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .join(Account, SearchProfile.account_id == Account.id)
            .filter(LeadSheetExport.id == export_id)
            .first()
        )
        if not row:
            return None

        export, conversation, listing, search_profile, account = row
        from app.proxy.url import build_account_proxy_url

        return {
            "export_id": export.id,
            "conversation_id": conversation.id,
            "thread_id": conversation.thread_id,
            "listing_pk": listing.id,
            "listing_id": listing.listing_id,
            "property_url": listing.property_url,
            "phone_number": conversation.extracted_phone,
            "phone_found_at": conversation.phone_found_at,
            "landlord_name": listing.landlord_name,
            "address": listing.property_address,
            "bedrooms": listing.bedrooms,
            "bathrooms": listing.bathrooms,
            "rent_pcm": listing.rent_pcm,
            "search_location": search_profile.location,
            "account_id": account.id,
            "account_email": account.email,
            "proxy_url": build_account_proxy_url(account),
            "attempt_count": export.attempt_count,
            "current_status": export.status,
        }


def mark_sheet_export_succeeded(
    export_id,
    *,
    destination_tab,
    destination_row,
    payload_hash,
):
    now = datetime.utcnow()
    with session_scope() as db:
        export = db.query(LeadSheetExport).filter(
            LeadSheetExport.id == export_id
        ).first()
        if not export:
            return False

        export.status = "EXPORTED"
        export.attempt_count = (export.attempt_count or 0) + 1
        export.next_attempt_at = None
        export.processing_started_at = None
        export.last_error = None
        export.destination_tab = destination_tab
        export.destination_row = destination_row
        export.payload_hash = payload_hash
        export.exported_at = now
        export.updated_at = now
        db.commit()
        return True


def mark_sheet_export_failed(
    export_id,
    *,
    error,
    next_attempt_at=None,
    permanent=False,
):
    now = datetime.utcnow()
    with session_scope() as db:
        export = db.query(LeadSheetExport).filter(
            LeadSheetExport.id == export_id
        ).first()
        if not export:
            return False

        export.status = "PERMANENT_FAILURE" if permanent else "FAILED"
        export.attempt_count = (export.attempt_count or 0) + 1
        export.next_attempt_at = None if permanent else next_attempt_at
        export.processing_started_at = None
        export.last_error = str(error)[:4000]
        export.updated_at = now
        db.commit()
        return True


def reset_sheet_export_to_pending(export_id):
    now = datetime.utcnow()
    with session_scope() as db:
        export = db.query(LeadSheetExport).filter(
            LeadSheetExport.id == export_id
        ).first()
        if not export:
            return False
        export.status = "PENDING"
        export.next_attempt_at = now
        export.processing_started_at = None
        export.last_error = None
        export.updated_at = now
        db.commit()
        return True


def reset_sheet_export_by_listing_id(listing_id):
    now = datetime.utcnow()
    with session_scope() as db:
        export = (
            db.query(LeadSheetExport)
            .join(
                Conversation,
                LeadSheetExport.conversation_id == Conversation.id,
            )
            .join(Listing, Conversation.listing_id == Listing.id)
            .filter(Listing.listing_id == str(listing_id))
            .first()
        )
        if not export:
            return None
        export.status = "PENDING"
        export.next_attempt_at = now
        export.processing_started_at = None
        export.last_error = None
        export.updated_at = now
        db.commit()
        return export.id


def get_sheet_export_statuses(status=None, limit=100, listing_id=None):
    with session_scope() as db:
        query = (
            db.query(LeadSheetExport, Conversation, Listing)
            .join(
                Conversation,
                LeadSheetExport.conversation_id == Conversation.id,
            )
            .join(Listing, Conversation.listing_id == Listing.id)
        )
        if status and status != "ALL":
            query = query.filter(LeadSheetExport.status == status)
        if listing_id:
            query = query.filter(Listing.listing_id == str(listing_id))

        rows = (
            query.order_by(LeadSheetExport.updated_at.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return [
            {
                "export_id": export.id,
                "status": export.status,
                "attempt_count": export.attempt_count,
                "next_attempt_at": _utc(export.next_attempt_at),
                "last_error": export.last_error,
                "destination_tab": export.destination_tab,
                "destination_row": export.destination_row,
                "payload_hash": export.payload_hash,
                "created_at": _utc(export.created_at),
                "updated_at": _utc(export.updated_at),
                "exported_at": _utc(export.exported_at),
                "conversation_id": conversation.id,
                "thread_id": conversation.thread_id,
                "listing_id": listing.listing_id,
                "property_url": listing.property_url,
            }
            for export, conversation, listing in rows
        ]


def backfill_sheet_export_outbox(dry_run=True, location=None):
    with session_scope() as db:
        query = (
            db.query(Conversation, Listing, SearchProfile, LeadSheetExport)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .outerjoin(
                LeadSheetExport,
                LeadSheetExport.conversation_id == Conversation.id,
            )
            .filter(
                Conversation.extracted_phone != None,
                Conversation.phone_found_at != None,
            )
            .order_by(Conversation.phone_found_at.asc())
        )
        if location:
            query = query.filter(
                SearchProfile.location.ilike(f"%{str(location).strip()}%")
            )

        matched_rows = query.all()
        eligible_rows = [
            (conversation, listing, profile)
            for conversation, listing, profile, export in matched_rows
            if export is None
        ]

        result = {
            "location_filter": location,
            "matched_phone_leads": len(matched_rows),
            "already_tracked": len(matched_rows) - len(eligible_rows),
            "eligible": len(eligible_rows),
            "created": 0,
            "leads": [
                {
                    "conversation_id": conversation.id,
                    "thread_id": conversation.thread_id,
                    "listing_id": listing.listing_id,
                    "property_url": listing.property_url,
                    "location": profile.location,
                    "phone_found_at": _utc(conversation.phone_found_at),
                }
                for conversation, listing, profile in eligible_rows
            ],
        }
        if dry_run:
            return result

        now = datetime.utcnow()
        for conversation, _, _ in eligible_rows:
            db.add(
                LeadSheetExport(
                    conversation_id=conversation.id,
                    status="PENDING",
                    next_attempt_at=now,
                )
            )
        db.commit()
        result["created"] = len(eligible_rows)
        return result


def save_ai_reply(
    thread_id,
    reply
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.last_ai_reply = reply
            conversation.status = "AI_REPLIED"
            db.commit()


def get_conversation_messages(thread_id):
    from app.utils.logger import logger
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            return []

        rows = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )

        result = []
        for message in rows:
            # All messages in this table are real OpenRent messages:
            # inbound rows come from save_inbound_messages (landlord messages
            # scraped from the page); outbound rows are written only after
            # send_reply() confirms the send succeeded.  AI drafts are stored
            # separately in conversation.last_ai_reply and must never appear here.
            logger.info(
                f"THREAD_MESSAGE_SOURCE thread_id={thread_id}"
                f" message_id={message.id} source=openrent"
                f" direction={message.direction}"
            )
            result.append({
                "id": message.id,
                "thread_id": thread_id,
                "direction": message.direction,
                "content": message.content,
                "created_at": message.created_at,
                "source": "openrent",
            })

        return result


def mark_listing_skipped(listing_id, reason="SKIPPED"):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.skip_reason = reason
            listing.processing_failed = False
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None
            db.commit()


def get_conversation_by_thread_id(
    thread_id
):
    with session_scope() as db:
        return db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()


def update_last_processed_message(
    thread_id,
    message
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.last_processed_message = message
            db.commit()


def phone_exists(phone):
    with session_scope() as db:
        exists = db.query(
            Conversation
        ).filter(
            Conversation.extracted_phone == phone
        ).first()

        return exists is not None


def get_landlord_by_profile_url(profile_url: str):
    with session_scope() as db:
        landlord = db.query(Landlord).filter(
            Landlord.profile_url == profile_url
        ).first()
        return landlord


def get_or_create_landlord(profile_url):
    with session_scope() as db:
        landlord = db.query(Landlord).filter(
            Landlord.profile_url == profile_url
        ).first()

        if landlord:
            return landlord

        landlord = Landlord(profile_url=profile_url)
        db.add(landlord)
        db.commit()
        db.refresh(landlord)

        return landlord


def update_landlord_scan(profile_url, property_count, is_agent):
    with session_scope() as db:
        landlord = db.query(Landlord).filter(
            Landlord.profile_url == profile_url
        ).first()

        if landlord is None:
            landlord = Landlord(profile_url=profile_url)
            db.add(landlord)

        landlord.property_count = property_count
        landlord.is_agent = is_agent
        landlord.last_checked_at = datetime.utcnow()
        db.commit()
        db.refresh(landlord)

        return landlord


def attach_landlord_to_listing(listing_id, landlord_id):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.landlord_id = landlord_id
            db.commit()


def archive_stale_listings(days: int = 30) -> int:
    """Archive uncontacted listings not seen within the given number of days."""
    threshold = datetime.utcnow() - timedelta(days=days)
    with session_scope() as db:
        stale = (
            db.query(Listing)
            .filter(
                Listing.listing_archived == False,
                Listing.message_sent == False,
                Listing.listing_last_seen != None,
                Listing.listing_last_seen < threshold,
            )
            .all()
        )
        for listing in stale:
            listing.listing_archived = True
        if stale:
            db.commit()
            from app.utils.logger import logger
            logger.info(f"ARCHIVED_LISTINGS_COUNT count={len(stale)}")
        return len(stale)


def mark_listing_skipped_agent(listing_id, property_count=None):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.skip_reason = "agent"
            listing.processing_failed = False
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None
            db.commit()


def get_due_viewing_cancellations(account_id=None, limit=25):
    """
    Return conversations whose viewing cancellation is due.

    Each conversation stores a randomised cancel_target_hours (3.2–4.8 h)
    set when the viewing was first confirmed.  A cancellation is due when:

        now >= viewing_datetime - cancel_target_hours

    The DB query uses a broad upper-bound filter (≤ 5 hours away) to pull
    candidates; the per-conversation target is then applied in Python.
    Safety guards: viewing not yet cancelled, cancellation not yet sent,
    and viewing still in the future.
    """
    from app.utils.logger import logger

    now = datetime.utcnow()
    upper_cutoff = now + timedelta(hours=5)

    with session_scope() as db:
        query = (
            db.query(Conversation, Listing, SearchProfile, Account)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .join(Account, SearchProfile.account_id == Account.id)
        )
        logger.info("VIEWING QUERY BUILT")

        query = query.filter(
            Conversation.viewing_datetime != None,
            Conversation.viewing_datetime <= upper_cutoff,
            Conversation.viewing_datetime > now,
            Conversation.viewing_cancelled == False,
            Conversation.cancel_required == True,
            Conversation.cancellation_sent_at == None,
            Conversation.viewing_confirmed == True,
            Conversation.conversation_stage == VIEWING_BOOKED,
            # phone_found and handoff_completed_at are NOT required:
            # cancellation is time-based and fires regardless of phone status.
            # The old handoff_completed_at filter was contradictory — mark_handoff_complete
            # sets stage=HANDOFF_COMPLETE, which conflicts with stage==VIEWING_BOOKED above.
        )

        if account_id is not None:
            query = query.filter(Account.id == account_id)

        logger.info("VIEWING FILTERS APPLIED")

        query = query.order_by(Conversation.viewing_datetime.asc())
        logger.info("VIEWING ORDERING APPLIED")

        query = query.limit(limit)
        logger.info("VIEWING LIMIT APPLIED")

        results = []
        for conversation, listing, search_profile, account in query.all():
            target_h = conversation.cancel_target_hours or 4.0
            cancel_at = conversation.viewing_datetime - timedelta(hours=target_h)

            if now < cancel_at:
                # Not yet in the cancellation window for this conversation
                continue

            hours_remaining = (
                conversation.viewing_datetime - now
            ).total_seconds() / 3600
            logger.info(
                f"CANCELLATION_ELIGIBLE thread_id={conversation.thread_id} "
                f"viewing_datetime={conversation.viewing_datetime} "
                f"viewing_confirmed={conversation.viewing_confirmed} "
                f"conversation_stage={conversation.conversation_stage} "
                f"target_hours={target_h} hours_remaining={hours_remaining:.1f}"
            )
            results.append({
                "thread_id": conversation.thread_id,
                "viewing_datetime": conversation.viewing_datetime,
                "viewing_confirmed": conversation.viewing_confirmed,
                "property_url": listing.property_url,
                "location": search_profile.location,
                "account_id": account.id,
                "conversation_stage": conversation.conversation_stage,
            })

        return results


def count_phones_today(account_id=None):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    with session_scope() as db:
        query = (
            db.query(Conversation)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                Conversation.extracted_phone != None,
                Conversation.phone_found_at != None,
                Conversation.phone_found_at >= start,
            )
        )

        if account_id is not None:
            query = query.filter(SearchProfile.account_id == account_id)

        return query.count()


def get_thread_property_location(thread_id):
    with session_scope() as db:
        row = (
            db.query(SearchProfile.location)
            .join(Listing, Listing.search_profile_id == SearchProfile.id)
            .join(Conversation, Conversation.listing_id == Listing.id)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )

        return row[0] if row else None


def get_travel_city(thread_id: str) -> str | None:
    with session_scope() as db:
        conv = db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
        return conv.travel_city if conv else None


def save_travel_city(thread_id: str, city: str) -> None:
    with session_scope() as db:
        conv = db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
        if conv:
            conv.travel_city = city
            db.commit()


def get_dashboard_leads(status=None):
    with session_scope() as db:
        query = (
            db.query(Conversation, Listing, SearchProfile, Account)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .join(Account, SearchProfile.account_id == Account.id)
        )

        if status and status != "ALL":
            query = query.filter(Conversation.status == status)

        rows = []

        for conversation, listing, search_profile, account in query.order_by(Conversation.created_at.desc()).all():
            persona = ensure_account_persona(account.id)
            rows.append({
                "thread_id": conversation.thread_id,
                "listing_id": listing.listing_id,
                "property_url": listing.property_url,
                "account_id": account.id,
                "account_email": account.email,
                "search_profile_id": search_profile.id,
                "location": search_profile.location,
                "price_min": search_profile.price_min,
                "price_max": search_profile.price_max,
                "bedrooms_min": search_profile.bedrooms_min,
                "bedrooms_max": search_profile.bedrooms_max,
                "area": search_profile.area,
                "pets_allowed": search_profile.pets_allowed,
                "status": conversation.status,
                "conversation_stage": conversation.conversation_stage,
                "viewing_datetime": conversation.viewing_datetime,
                "viewing_confirmed": conversation.viewing_confirmed,
                "viewing_cancelled": conversation.viewing_cancelled,
                "cancel_required": conversation.cancel_required,
                "cancellation_sent_at": conversation.cancellation_sent_at,
                "phone_requested_at": conversation.phone_requested_at,
                "phone_found_at": conversation.phone_found_at,
                "phone_number_shared_at": conversation.phone_number_shared_at,
                "landlord_asked_phone_at": conversation.landlord_asked_phone_at,
                "handoff_completed_at": conversation.handoff_completed_at,
                "landlord_attitude": conversation.landlord_attitude,
                "conversation_style": (
                    conversation.conversation_style
                    or (persona["conversation_style"] if persona else None)
                ),
                "last_stage_change": conversation.last_stage_change,
                "phone": conversation.extracted_phone or "",
                "phone_number": conversation.extracted_phone or "",
                "last_processed_message": conversation.last_processed_message or "",
                "last_ai_reply": conversation.last_ai_reply or "",
                "persona_name": persona["persona_name"] if persona else account.persona_name,
                "persona_partner_name": (
                    persona["persona_partner_name"] if persona else account.persona_partner_name
                ),
                "persona_job": persona["persona_job"] if persona else account.persona_job,
                "persona_partner_job": (
                    persona["persona_partner_job"] if persona else account.persona_partner_job
                ),
                "home_city": persona["home_city"] if persona else account.home_city,
                "persona_type": persona["persona_type"] if persona else account.persona_type,
                "household_description": persona["household_description"] if persona else None,
                "message_tone": persona["message_tone"] if persona else None,
                "mobile_number": persona["mobile_number"] if persona else None,
                "phone_fetching_type": persona["phone_fetching_type"] if persona else None,
                "message_strategy": persona["message_strategy"] if persona else None,
                "escalation_behavior": persona["escalation_behavior"] if persona else None,
                "conversation_goal": persona["conversation_goal"] if persona else None,
                "created_at": conversation.created_at,
                "last_message_at": conversation.last_message_at,
            })

        return rows


def get_dashboard_search_profiles():
    with session_scope() as db:
        profiles = (
            db.query(SearchProfile, Account)
            .join(Account, SearchProfile.account_id == Account.id)
            .order_by(SearchProfile.created_at.desc())
            .all()
        )

        rows = []

        for profile, account in profiles:
            rows.append({
                "id": profile.id,
                "account_id": account.id,
                "account_email": account.email,
                "location": profile.location,
                "price_min": profile.price_min,
                "price_max": profile.price_max,
                "bedrooms_min": profile.bedrooms_min,
                "bedrooms_max": profile.bedrooms_max,
                "area": profile.area,
                "pets_allowed": profile.pets_allowed,
                "active": profile.active,
                "created_at": profile.created_at,
            })

        return rows


def get_dashboard_search_profile(profile_id):
    with session_scope() as db:
        row = (
            db.query(SearchProfile, Account)
            .join(Account, SearchProfile.account_id == Account.id)
            .filter(SearchProfile.id == profile_id)
            .first()
        )

        if not row:
            return None

        profile, account = row

        return {
            "id": profile.id,
            "account_id": account.id,
            "account_email": account.email,
            "location": profile.location,
            "price_min": profile.price_min,
            "price_max": profile.price_max,
            "bedrooms_min": profile.bedrooms_min,
            "bedrooms_max": profile.bedrooms_max,
            "area": profile.area,
            "pets_allowed": profile.pets_allowed,
            "active": profile.active,
            "created_at": profile.created_at,
        }


def update_search_profile(
    profile_id,
    account_id=None,
    location=None,
    price_min=None,
    price_max=None,
    bedrooms_min=None,
    bedrooms_max=None,
    pets_allowed=None,
    area=None,
    active=None
):
    with session_scope() as db:
        profile = db.query(SearchProfile).filter(
            SearchProfile.id == profile_id
        ).first()

        if not profile:
            return None

        if account_id is not None:
            profile.account_id = account_id
        if location is not None:
            profile.location = location
        if price_min is not None:
            profile.price_min = price_min
        if price_max is not None:
            profile.price_max = price_max
        if bedrooms_min is not None:
            profile.bedrooms_min = bedrooms_min
        if bedrooms_max is not None:
            profile.bedrooms_max = bedrooms_max
        if area is not None:
            profile.area = area
        if pets_allowed is not None:
            profile.pets_allowed = pets_allowed
        if active is not None:
            profile.active = active

        db.commit()

    return get_dashboard_search_profile(profile_id)


def deactivate_search_profile(profile_id):
    return update_search_profile(
        profile_id=profile_id,
        active=False
    )


# ---------------- LOCATIONS ----------------

def _serialize_location(loc) -> dict:
    return {
        "id": loc.id,
        "name": loc.name,
        "term_value": loc.term_value,
        "active": loc.active,
        "created_at": loc.created_at,
    }


def get_locations(active_only: bool = False):
    from app.db.models import Location
    with session_scope() as db:
        q = db.query(Location)
        if active_only:
            q = q.filter(Location.active == True)
        return [_serialize_location(loc) for loc in q.order_by(Location.name.asc()).all()]


def create_location(name: str, term_value: str, active: bool = True):
    from app.db.models import Location
    with session_scope() as db:
        loc = Location(name=name, term_value=term_value, active=active)
        db.add(loc)
        db.commit()
        db.refresh(loc)
        return _serialize_location(loc)


def update_location(location_id: int, name: str | None = None, term_value: str | None = None, active: bool | None = None):
    from app.db.models import Location
    with session_scope() as db:
        loc = db.query(Location).filter(Location.id == location_id).first()
        if not loc:
            return None
        if name is not None:
            loc.name = name
        if term_value is not None:
            loc.term_value = term_value
        if active is not None:
            loc.active = active
        db.commit()
        db.refresh(loc)
        return _serialize_location(loc)


def delete_location(location_id: int):
    from app.db.models import Location
    with session_scope() as db:
        loc = db.query(Location).filter(Location.id == location_id).first()
        if not loc:
            return None, "not_found"
        db.delete(loc)
        db.commit()
        return {"deleted": True, "id": location_id}, None


# ---------------- FAILED ACCOUNTS ----------------

def get_failed_accounts():
    with session_scope() as db:
        accounts = (
            db.query(Account)
            .options(joinedload(Account.proxy))
            .filter(Account.failed == True)
            .order_by(Account.failed_at.desc())
            .all()
        )
        results = []
        for account in accounts:
            base = serialize_account(account)
            base["messages_sent"] = _count_account_outbound_messages(db, account.id, days=3)
            base["replies_received"] = _count_account_inbound_messages(db, account.id, days=3)
            results.append(base)
        return results


def get_failed_account_count() -> int:
    with session_scope() as db:
        return db.query(Account).filter(Account.failed == True).count()


def mark_account_failed(account_id: int, reason: str):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return
        account.failed = True
        account.failed_at = datetime.utcnow()
        account.failure_reason = reason
        db.commit()


def clear_account_failed(account_id: int):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None
        account.failed = False
        account.failed_at = None
        account.failure_reason = None
        db.commit()
        db.refresh(account)
        return serialize_account(account)


def _count_account_outbound_messages(db, account_id: int, days: int = 3) -> int:
    since = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Listing, Conversation.listing_id == Listing.id)
        .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
        .filter(
            SearchProfile.account_id == account_id,
            Message.direction == "outbound",
            Message.created_at >= since,
        )
        .count()
    )


def _count_account_inbound_messages(db, account_id: int, days: int = 3) -> int:
    since = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Listing, Conversation.listing_id == Listing.id)
        .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
        .filter(
            SearchProfile.account_id == account_id,
            Message.direction == "inbound",
            Message.created_at >= since,
        )
        .count()
    )


def _count_account_outbound_on_day(db, account_id: int, day_start: datetime, day_end: datetime) -> int:
    return (
        db.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Listing, Conversation.listing_id == Listing.id)
        .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
        .filter(
            SearchProfile.account_id == account_id,
            Message.direction == "outbound",
            Message.created_at >= day_start,
            Message.created_at < day_end,
        )
        .count()
    )


def detect_and_mark_failed_accounts():
    """
    Mark accounts as failed if they sent messages for 2 consecutive calendar days
    with no inbound (landlord) replies in that window.
    """
    from app.utils.scheduling import uk_now

    now_uk = uk_now()
    today = now_uk.date()

    # Day windows in UTC (approximate — close enough for daily detection)
    day0_start = datetime(today.year, today.month, today.day) - timedelta(days=1)
    day0_end = datetime(today.year, today.month, today.day)
    day1_start = day0_start - timedelta(days=1)
    day1_end = day0_start

    with session_scope() as db:
        accounts = db.query(Account).options(joinedload(Account.proxy)).filter(Account.active == True).all()

        for account in accounts:
            if account.failed:
                continue

            sent_day0 = _count_account_outbound_on_day(db, account.id, day0_start, day0_end)
            sent_day1 = _count_account_outbound_on_day(db, account.id, day1_start, day1_end)

            if sent_day0 == 0 or sent_day1 == 0:
                continue

            replies = _count_account_inbound_messages(db, account.id, days=2)

            if replies == 0:
                account.failed = True
                account.failed_at = datetime.utcnow()
                account.failure_reason = (
                    f"No landlord replies received after 2 consecutive days of outreach "
                    f"({sent_day1} messages on day 1, {sent_day0} messages on day 2)."
                )

        db.commit()
