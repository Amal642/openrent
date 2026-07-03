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
from datetime import datetime

from app.alerts import events
from app.alerts.manager import AlertManager
from app.config import settings
from app.db.repository import get_active_accounts, get_app_setting
from app.utils.logger import logger

HEALTHY_PROXY_STATUSES = {"ok", "healthy"}
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


async def run_forever(manager: AlertManager) -> None:
    logger.info(f"ALERT_HEALTH_CHECKS_STARTED interval_seconds={settings.ALERT_HEALTH_CHECK_SECONDS}")
    while True:
        try:
            await _check_proxies(manager)
            await _check_whatsapp(manager)
        except Exception:
            logger.exception("ALERT_HEALTH_CHECK_TICK_FAILED")
        await asyncio.sleep(settings.ALERT_HEALTH_CHECK_SECONDS)
