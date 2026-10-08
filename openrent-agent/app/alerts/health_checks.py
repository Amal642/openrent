"""
Active health checks for signals that fail silently: proxy down, WhatsApp
session dropped. Runs on a timer in the alert-bot process, independent of
scripts/run_workers.py and the WhatsApp browser worker (both run as separate
processes). Recovery detection is DB-driven rather than in-memory: each tick
recomputes health directly and uses AlertSignature.active (already durable)
as the source of truth for "was this already alerting", so a restart of this
process can't cause a missed recovery notice or a stuck alert.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from app.alerts import events
from app.alerts.manager import AlertManager
from app.config import settings
from app.db.repository import get_active_accounts, get_app_setting
from app.services import page_health
from app.utils.logger import logger

HEALTHY_PROXY_STATUSES = {"ok", "healthy", "degraded", "slow"}
# Browser worker heartbeats every ~10-15 min (see _poll_loop); allow slack
# before treating a missing heartbeat as "the process is probably dead".
WHATSAPP_HEARTBEAT_STALE_SECONDS = 40 * 60
WHATSAPP_TRANSIENT_STATUSES = {"starting", "reconnecting"}


def _proxy_is_healthy(account) -> bool:
    proxy = getattr(account, "proxy", None)
    if not proxy or not proxy.is_active:
        return False
    proxy_status = str(getattr(account, "proxy_status", "") or "").lower()
    health_status = str(getattr(proxy, "health_status", "") or "").lower()
    return proxy_status in HEALTHY_PROXY_STATUSES or health_status in HEALTHY_PROXY_STATUSES


async def _check_proxies(manager: AlertManager) -> None:
    accounts = await asyncio.to_thread(get_active_accounts)
    for account in accounts:
        if not account.proxy_id:
            continue

        title = f"Proxy unhealthy for account {account.id}"
        signature = events.make_signature("proxy", title, None)

        if _proxy_is_healthy(account):
            cleared = await asyncio.to_thread(manager.clear_signature_if_active, signature)
            if cleared:
                await manager.send_recovery_notice("proxy", title)
            continue

        proxy = getattr(account, "proxy", None)
        events.report_error(
            "proxy",
            title,
            detail=(
                f"proxy_status={account.proxy_status!r} "
                f"health_status={getattr(proxy, 'health_status', None)!r} "
                f"proxy_active={getattr(proxy, 'is_active', None)}"
            ),
            context={"account_id": account.id, "proxy_id": account.proxy_id},
        )


async def _check_whatsapp(manager: AlertManager) -> None:
    title = "WhatsApp session needs attention"
    signature = events.make_signature("whatsapp", title, None)

    raw = await asyncio.to_thread(get_app_setting, "whatsapp_worker_heartbeat")
    if not raw:
        # No heartbeat recorded yet (worker never started this deployment) —
        # nothing to alert on until it's actually run once.
        return

    try:
        data = json.loads(raw)
        status = data.get("status")
        heartbeat_at = datetime.fromisoformat(data.get("at"))
    except Exception:
        logger.warning(f"ALERT_WHATSAPP_HEARTBEAT_UNPARSEABLE raw={raw!r}")
        return

    stale = (datetime.utcnow() - heartbeat_at).total_seconds() > WHATSAPP_HEARTBEAT_STALE_SECONDS
    healthy = status == "connected" and not stale

    if healthy:
        cleared = await asyncio.to_thread(manager.clear_signature_if_active, signature)
        if cleared:
            await manager.send_recovery_notice("whatsapp", title)
        return

    if status in WHATSAPP_TRANSIENT_STATUSES and not stale:
        return

    events.report_error(
        "whatsapp",
        title,
        detail=f"status={status!r} stale={stale} last_heartbeat={data.get('at')}",
        context=data,
    )


# ---- OpenRent page health (see app/services/page_health.py) ----
#
# A step is "fleet-failing" when, in the last hour, it failed at least
# PAGE_MIN_FAILS times, at a PAGE_FAIL_RATE or worse, on PAGE_MIN_ACCOUNTS or
# more accounts. One account failing is that account's problem (proxy, its own
# restrictions); several at once is OpenRent changing the page. It recovers
# once it has PAGE_RECOVERY_OKS successes and a low failure rate again.
PAGE_WINDOW_MINUTES = 60
PAGE_MIN_FAILS = 5
PAGE_FAIL_RATE = 0.6
PAGE_MIN_ACCOUNTS = 3
PAGE_RECOVERY_OKS = 3
PAGE_RECOVERY_RATE = 0.3
PAGE_BREAKER_MINUTES = 90
LOGIN_WINDOW_HOURS = 6
LOGIN_MIN_FAILS = 3
STEP_EVENT_RETENTION_DAYS = 14

_last_step_prune: datetime | None = None


def evaluate_step_health(rows) -> dict:
    """rows: (step, account_id, ok, detail) tuples from the last window.
    Returns {step: {"status": "failing"|"recovered"|"quiet", ...stats}}."""
    stats: dict = {}
    for step, account_id, ok, detail in rows:
        s = stats.setdefault(
            step, {"ok": 0, "fail": 0, "fail_accounts": set(), "sample": None}
        )
        if ok:
            s["ok"] += 1
        else:
            s["fail"] += 1
            if account_id is not None:
                s["fail_accounts"].add(account_id)
            if detail and not s["sample"]:
                s["sample"] = detail
    for s in stats.values():
        total = s["ok"] + s["fail"]
        s["rate"] = s["fail"] / total if total else 0.0
        if (
            s["fail"] >= PAGE_MIN_FAILS
            and s["rate"] >= PAGE_FAIL_RATE
            and len(s["fail_accounts"]) >= PAGE_MIN_ACCOUNTS
        ):
            s["status"] = "failing"
        elif s["ok"] >= PAGE_RECOVERY_OKS and s["rate"] < PAGE_RECOVERY_RATE:
            s["status"] = "recovered"
        else:
            s["status"] = "quiet"
    return stats


def failing_login_accounts(rows) -> dict:
    """rows: (account_id, ok, detail) login attempts in the login window.
    Returns {account_id: (fail_count, sample_detail)} for accounts that kept
    failing with no success at all."""
    per: dict = {}
    for account_id, ok, detail in rows:
        if account_id is None:
            continue
        p = per.setdefault(account_id, {"ok": 0, "fail": 0, "sample": None})
        if ok:
            p["ok"] += 1
        else:
            p["fail"] += 1
            p["sample"] = p["sample"] or detail
    return {
        acc: (p["fail"], p["sample"])
        for acc, p in per.items()
        if p["ok"] == 0 and p["fail"] >= LOGIN_MIN_FAILS
    }


def _step_rows(since: datetime, step: str | None = None):
    from app.db.models import StepHealthEvent
    from app.db.repository import session_scope

    with session_scope() as db:
        q = db.query(
            StepHealthEvent.step,
            StepHealthEvent.account_id,
            StepHealthEvent.ok,
            StepHealthEvent.detail,
            StepHealthEvent.created_at,
        ).filter(StepHealthEvent.created_at >= since)
        if step:
            q = q.filter(StepHealthEvent.step == step)
        return q.all()


def _signature_active(signature: str) -> bool:
    from app.db.models import AlertSignature
    from app.db.repository import session_scope

    with session_scope() as db:
        row = db.query(AlertSignature).filter(AlertSignature.signature == signature).first()
        return bool(row and row.active)


def _prune_step_events() -> None:
    global _last_step_prune
    from app.db.models import StepHealthEvent
    from app.db.repository import session_scope

    now = datetime.utcnow()
    if _last_step_prune and now - _last_step_prune < timedelta(hours=1):
        return
    _last_step_prune = now
    with session_scope() as db:
        db.query(StepHealthEvent).filter(
            StepHealthEvent.created_at < now - timedelta(days=STEP_EVENT_RETENTION_DAYS)
        ).delete(synchronize_session=False)
        db.commit()


def page_health_title(step: str) -> str:
    return f"OpenRent page check failing: {page_health.STEP_LABELS.get(step, step)}"


async def _check_page_health(manager: AlertManager) -> None:
    since = datetime.utcnow() - timedelta(minutes=PAGE_WINDOW_MINUTES)
    rows = await asyncio.to_thread(_step_rows, since)
    # Failures from before a manual /resume are stale evidence: drop them so a
    # fixed step is not paused again straight away.
    resumed = {
        scope: await asyncio.to_thread(page_health.resumed_at, scope)
        for scope in set(page_health.BREAKER_SCOPES.values())
    }
    rows = [
        (step, account_id, ok, detail)
        for step, account_id, ok, detail, created_at in rows
        if not (
            resumed.get(page_health.BREAKER_SCOPES.get(step))
            and created_at < resumed[page_health.BREAKER_SCOPES[step]]
        )
    ]
    stats = evaluate_step_health(rows)

    for step, s in stats.items():
        title = page_health_title(step)
        signature = events.make_signature("page_health", title, None)
        scope = page_health.BREAKER_SCOPES.get(step)

        if s["status"] == "failing":
            if scope and not await asyncio.to_thread(page_health.is_paused, scope):
                await asyncio.to_thread(
                    page_health.trip_breaker,
                    scope,
                    PAGE_BREAKER_MINUTES,
                    f"{step} failing {s['fail']}/{s['fail'] + s['ok']}",
                )
            if await asyncio.to_thread(_signature_active, signature):
                continue
            accounts = ", ".join(str(a) for a in sorted(s["fail_accounts"]))
            action = (
                f"{scope.capitalize()} is paused fleet-wide for {PAGE_BREAKER_MINUTES} min "
                "and resumes by itself; it pauses again if the step is still failing."
                if scope
                else "Nothing was paused: this step fails safe, but that part of the bot is not working."
            )
            events.report_error(
                "page_health",
                title,
                detail=(
                    f"{s['fail']} of {s['fail'] + s['ok']} attempts failed in the last "
                    f"{PAGE_WINDOW_MINUTES} min across accounts {accounts}. "
                    f"Example: {s['sample'] or 'n/a'}. {action} "
                    "OpenRent probably changed this page; the saved HTML and screenshots "
                    "are in debug/ and screenshots/ on the server."
                ),
                context={"step": step, "fail": s["fail"], "ok": s["ok"], "accounts": sorted(s["fail_accounts"])},
            )
        elif s["status"] == "recovered":
            if scope:
                await asyncio.to_thread(page_health.clear_breaker, scope)
            cleared = await asyncio.to_thread(manager.clear_signature_if_active, signature)
            if cleared:
                await manager.send_recovery_notice("page_health", title)

    # Per-account login failures: never alerted before, and a stuck login
    # quietly takes an account out of the fleet.
    login_since = datetime.utcnow() - timedelta(hours=LOGIN_WINDOW_HOURS)
    login_rows = [
        (account_id, ok, detail)
        for _step, account_id, ok, detail, _at in await asyncio.to_thread(
            _step_rows, login_since, page_health.LOGIN
        )
    ]
    failing = failing_login_accounts(login_rows)
    seen_accounts = {account_id for account_id, _ok, _d in login_rows if account_id is not None}
    for account_id in seen_accounts:
        title = f"Login failing for account {account_id}"
        if account_id in failing:
            if await asyncio.to_thread(
                _signature_active, events.make_signature("login", title, None)
            ):
                continue
            count, sample = failing[account_id]
            events.report_error(
                "login",
                title,
                detail=(
                    f"{count} failed logins and no successful one in the last "
                    f"{LOGIN_WINDOW_HOURS}h. Last error: {sample or 'n/a'}. "
                    "The account backs off (up to 24h after 5 failures) and does nothing meanwhile."
                ),
                context={"account_id": account_id},
            )
        else:
            signature = events.make_signature("login", title, None)
            cleared = await asyncio.to_thread(manager.clear_signature_if_active, signature)
            if cleared:
                await manager.send_recovery_notice("login", title)

    await asyncio.to_thread(_prune_step_events)


async def run_forever(manager: AlertManager) -> None:
    logger.info(f"ALERT_HEALTH_CHECKS_STARTED interval_seconds={settings.ALERT_HEALTH_CHECK_SECONDS}")
    while True:
        try:
            await _check_proxies(manager)
            await _check_whatsapp(manager)
        except Exception:
            logger.exception("ALERT_HEALTH_CHECK_TICK_FAILED")
        try:
            await _check_page_health(manager)
        except Exception:
            logger.exception("ALERT_PAGE_HEALTH_CHECK_FAILED")
        await asyncio.sleep(settings.ALERT_HEALTH_CHECK_SECONDS)
