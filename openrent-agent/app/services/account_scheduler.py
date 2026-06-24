import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.repository import (
    get_active_accounts,
    is_account_on_cooldown,
)
from app.utils.logger import logger
from app.utils.scheduling import UK_TZ, is_operating_hours, uk_now


SCHEDULER_INTERVAL_SECONDS = 60
MAX_PARALLEL_WORKERS = settings.MAX_PARALLEL_WORKERS
IN_FLIGHT_STATUSES = {"running", "queued", "stopping", "retrying"}
HEALTHY_PROXY_STATUSES = {"ok", "healthy", "degraded", "slow"}
STALE_HEARTBEAT_MINUTES = 10


def _worker_status(account) -> str:
    return str(getattr(account, "worker_status", "") or "").lower()


def _proxy_is_healthy(account) -> bool:
    proxy = getattr(account, "proxy", None)
    if not proxy or not proxy.is_active:
        return False

    proxy_status = str(getattr(account, "proxy_status", "") or "").lower()
    health_status = str(getattr(proxy, "health_status", "") or "").lower()
    return (
        proxy_status in HEALTHY_PROXY_STATUSES
        or health_status in HEALTHY_PROXY_STATUSES
    )


def reset_stale_workers():
    """Reset accounts stuck in running/queued with a stale heartbeat (OOM kill survivor)."""
    from app.db.connection import SessionLocal
    from app.db.models import Account as _Account

    stale_before = datetime.utcnow() - timedelta(minutes=STALE_HEARTBEAT_MINUTES)
    db = SessionLocal()
    try:
        stale = (
            db.query(_Account)
            .filter(
                _Account.worker_status.in_(list(IN_FLIGHT_STATUSES)),
                _Account.worker_last_heartbeat < stale_before,
            )
            .all()
        )
        for account in stale:
            logger.info(
                f"STALE_WORKER_RESET account_id={account.id} "
                f"email={account.email} "
                f"was_status={account.worker_status} "
                f"last_heartbeat={account.worker_last_heartbeat}"
            )
            account.worker_status = "idle"
            account.current_worker_phase = "stale_reset"
        if stale:
            db.commit()
    except Exception as exc:
        logger.warning(f"reset_stale_workers failed: {exc}")
        db.rollback()
    finally:
        db.close()


def _select_accounts(accounts):
    selected = []
    busy_proxy_ids = {
        account.proxy_id
        for account in accounts
        if account.proxy_id and _worker_status(account) in IN_FLIGHT_STATUSES
    }
    selected_proxy_ids = set()

    for account in accounts:
        worker_status_val = _worker_status(account)
        proxy = getattr(account, "proxy", None)
        proxy_assigned = proxy is not None
        proxy_healthy = _proxy_is_healthy(account)
        permanently_failed_val = bool(getattr(account, "permanently_failed", False))
        cooldown_until = getattr(account, "cooldown_until", None)
        on_cooldown = is_account_on_cooldown(account.id)

        # Convert cooldown_until (UTC naive) to BST for human-readable log
        if cooldown_until:
            cooldown_uk = cooldown_until.replace(tzinfo=timezone.utc).astimezone(UK_TZ)
            cooldown_display = cooldown_uk.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            cooldown_display = "none"

        session_status_val = str(getattr(account, "session_status", "") or "").lower()
        login_failures = getattr(account, "session_auth_failures", 0) or 0

        skip_reason = None
        if permanently_failed_val:
            skip_reason = "PERMANENT_FAILURE"
        elif session_status_val == "login_failed" and login_failures >= 5:
            skip_reason = "LOGIN_FAILED"
        elif worker_status_val in IN_FLIGHT_STATUSES:
            skip_reason = f"WORKER_{worker_status_val.upper()}"
        elif on_cooldown:
            skip_reason = "COOLDOWN"
        elif not proxy_assigned:
            skip_reason = "NO_PROXY"
        elif not proxy_healthy:
            skip_reason = "PROXY_UNHEALTHY"

        eligible = skip_reason is None

        if eligible:
            if account.proxy_id in busy_proxy_ids or account.proxy_id in selected_proxy_ids:
                skip_reason = "PROXY_BUSY"
                eligible = False

        logger.info(
            f"ACCOUNT_ELIGIBILITY "
            f"account_id={account.id} "
            f"email={account.email} "
            f"worker_status={worker_status_val} "
            f"cooldown_until={cooldown_display} "
            f"cooldown_expired={not on_cooldown} "
            f"proxy_id={account.proxy_id} "
            f"proxy_assigned={proxy_assigned} "
            f"proxy_healthy={proxy_healthy} "
            f"permanently_failed={permanently_failed_val} "
            f"eligible={eligible} "
            f"skip_reason={skip_reason or 'none'}"
        )

        if eligible:
            selected.append(account)
            selected_proxy_ids.add(account.proxy_id)

    return selected


async def run_scheduler_cycle():
    logger.info("Scheduler cycle started")
    current_uk_time = uk_now()
    logger.info(f"Current UK time: {current_uk_time.strftime('%Y-%m-%d %H:%M %Z')}")

    if not is_operating_hours(current_uk_time):
        logger.info("Outside operating hours. Skipping scheduler cycle.")
        return

    reset_stale_workers()

    accounts = get_active_accounts()

    in_flight_count = sum(
        1 for a in accounts if _worker_status(a) in IN_FLIGHT_STATUSES
    )
    busy_proxy_ids = {
        a.proxy_id
        for a in accounts
        if a.proxy_id and _worker_status(a) in IN_FLIGHT_STATUSES
    }
    proxy_capacity = len({
        a.proxy_id
        for a in accounts
        if a.proxy_id
        and _proxy_is_healthy(a)
        and a.proxy_id not in busy_proxy_ids
    })

    available_slots = max(0, MAX_PARALLEL_WORKERS - in_flight_count)

    logger.info(
        f"ACTIVE_WORKERS={in_flight_count} "
        f"PROXY_CAPACITY={proxy_capacity} "
        f"MAX_PARALLEL_WORKERS={MAX_PARALLEL_WORKERS} "
        f"AVAILABLE_SLOTS={available_slots}"
    )

    selected = _select_accounts(accounts)
    logger.info(f"QUEUED_ACCOUNTS={len(selected)} will_start={min(len(selected), available_slots)}")

    if available_slots == 0:
        logger.info("MAX_PARALLEL_WORKERS reached, no new accounts will be started this cycle")
        return

    from app.workers.account_worker import start_account_worker

    launched = 0
    for account in selected:
        if launched >= available_slots:
            logger.info(
                f"MAX_PARALLEL_WORKERS={MAX_PARALLEL_WORKERS} reached, "
                f"deferring {len(selected) - launched} remaining account(s)"
            )
            break

        logger.info(f"Queueing account {account.id}")
        result = await start_account_worker(account.id)
        if result.get("queued"):
            launched += 1
        else:
            logger.info(
                f"Scheduler skipped account {account.id}: "
                f"{result.get('reason') or 'not_queued'}"
            )


async def scheduler_loop():
    while True:
        try:
            await run_scheduler_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Scheduler cycle failed: {exc}")

        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


def start_account_scheduler():
    return asyncio.create_task(scheduler_loop(), name="account-scheduler")


async def stop_account_scheduler(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
