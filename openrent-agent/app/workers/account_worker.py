import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from rq import Retry

from app.utils.logger import logger

from app.browser.launcher import (
    launch_browser
)

from app.browser.auth import (
    login
)

from scripts.process_listings import (
    process_account_listings
)

from scripts.scrape_listings import (
    scrape_account_listings
)

from scripts.process_replies import (
    process_account_replies
)

from scripts.process_viewing_reminders import (
    process_account_viewing_reminders
)

from app.db.repository import (
    account_stop_requested,
    get_active_accounts,
    is_account_on_cooldown,
    set_account_cooldown,
    should_scrape_now,
    update_account_worker_state,
    update_proxy_health,
)
from app.proxy.check_proxy import check_proxy

from app.queue.queues import worker_queue
from app.utils.scheduling import is_operating_hours

ACTIVE_WORKERS = {}
ACTIVE_BROWSER_RESOURCES = {}
IN_FLIGHT_STATUSES = {"running", "queued", "stopping", "retrying"}
HEALTHY_PROXY_STATUSES = {"ok", "healthy"}


def _proxy_is_healthy(account):
    proxy = getattr(account, "proxy", None)
    if not proxy or not proxy.is_active:
        return False

    proxy_status = str(getattr(account, "proxy_status", "") or "").lower()
    health_status = str(getattr(proxy, "health_status", "") or "").lower()
    return (
        proxy_status in HEALTHY_PROXY_STATUSES
        or health_status in HEALTHY_PROXY_STATUSES
    )


def _status_is_in_flight(account):
    return str(account.worker_status or "").lower() in IN_FLIGHT_STATUSES


def _proxy_url_for_account(account):
    """
    Build a proxy URL for the Playwright proxy option.
    Prefers the linked Proxy record (proxy_id), falls back to legacy fields.
    """
    linked = getattr(account, "proxy", None)
    if linked and linked.is_active and linked.host:
        server = f"http://{linked.host}:{linked.port}"
        if not linked.username:
            return server
        username = quote(linked.username, safe="")
        password = quote(linked.password or "", safe="")
        return f"http://{username}:{password}@{linked.host}:{linked.port}"

    proxy_server = (account.proxy_server or "").strip()
    if not proxy_server:
        return None

    parsed = urlsplit(
        proxy_server if "://" in proxy_server else f"http://{proxy_server}"
    )
    if not account.proxy_username:
        return urlunsplit(parsed)

    username = quote(account.proxy_username, safe="")
    password = quote(account.proxy_password or "", safe="")
    credentials = f"{username}:{password}@"
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
    return urlunsplit(
        (
            parsed.scheme,
            f"{credentials}{netloc}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


async def _heartbeat_loop(account_id, phase_getter):
    while True:
        update_account_worker_state(
            account_id,
            "running",
            phase=phase_getter(),
        )
        await asyncio.sleep(45)


async def run_account_worker(account):

    worker_id = f"account-{account.id}-{uuid4().hex[:8]}"
    phase = "send_and_reply"

    if not is_operating_hours():
        logger.info("Outside operating hours")
        logger.info("Skipping worker cycle")
        update_account_worker_state(
            account.id,
            "idle",
            phase="outside_operating_hours",
        )
        return

    logger.info(
        f"Starting worker for "
        f"account {account.email}"
    )

    update_account_worker_state(
        account.id,
        "running",
        phase=phase
    )

    playwright = None
    browser = None
    context = None
    heartbeat_task = None

    try:
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(account.id, lambda: phase)
        )

        proxy_url = _proxy_url_for_account(account)
        if proxy_url:
            phase = "proxy_check"
            update_account_worker_state(
                account.id,
                "running",
                phase=phase,
            )
            proxy_result = await asyncio.to_thread(check_proxy, proxy_url)
            update_proxy_health(account.id, proxy_result)

            if not proxy_result.get("healthy"):
                error = proxy_result.get("error") or "Proxy health check failed"
                logger.error(
                    f"Proxy health check failed for {account.email}: {error}"
                )
                update_account_worker_state(
                    account.id,
                    "proxy_error",
                    phase="proxy_error",
                    error=error,
                    retry_reason=error,
                    retry_next_at=datetime.utcnow() + timedelta(minutes=1),
                )
                phase = "proxy_error"
                return

        phase = "launching_browser"
        update_account_worker_state(
            account.id,
            "running",
            phase=phase,
        )

        playwright, browser, context, page = (
            await launch_browser(account)
        )

        ACTIVE_BROWSER_RESOURCES[account.id] = {
            "playwright": playwright,
            "browser": browser,
            "context": context,
        }

        phase = "authenticating"
        update_account_worker_state(
            account.id,
            "running",
            phase=phase,
        )

        try:
            await login(
                page,
                context,
                account
            )
        except Exception as exc:
            phase = "login_error"
            update_account_worker_state(
                account.id,
                "login_error",
                phase="login_error",
                error=str(exc),
            )
            raise

        phase = "send_and_reply"
        update_account_worker_state(
            account.id,
            "running",
            phase=phase
        )

        # =====================================================
        # STOP CHECK BEFORE LISTING PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"listing phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # SCRAPING PHASE — once per calendar day per account
        # =====================================================

        if should_scrape_now(account.id):
            phase = "scraping"
            update_account_worker_state(
                account.id,
                "running",
                phase=phase,
            )
            try:
                await scrape_account_listings(account, page)
            except Exception as exc:
                logger.exception(
                    f"Scraping failed for {account.email}: {exc}"
                )
            phase = "send_and_reply"
            update_account_worker_state(
                account.id,
                "running",
                phase=phase,
            )

        # =====================================================
        # INITIAL OUTREACH PHASE (limited to 8/day via can_send_message)
        # =====================================================

        await process_account_listings(
            account,
            page,
            worker_id=worker_id
        )

        # =====================================================
        # STOP CHECK BEFORE REPLY PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"reply phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # AI REPLY PROCESSING PHASE
        # =====================================================

        await process_account_replies(
            account,
            page,
            worker_id=worker_id
        )

        # =====================================================
        # STOP CHECK BEFORE REMINDER PROCESSING
        # =====================================================

        if account_stop_requested(account.id):

            logger.info(
                f"Worker stop requested before "
                f"reminder phase for {account.email}"
            )

            phase = "stopped"
            return

        # =====================================================
        # VIEWING REMINDER PHASE
        # =====================================================

        await process_account_viewing_reminders(
            account,
            page,
            worker_id=worker_id
        )

        # =====================================================
        # SUCCESSFUL COMPLETION
        # =====================================================

        update_account_worker_state(
            account.id,
            "completed",
            phase="completed"
        )
        set_account_cooldown(account.id)
        phase = "completed"

    except asyncio.CancelledError:

        logger.info(
            f"Worker cancellation requested "
            f"for {account.email}"
        )

        phase = "stopped"

        update_account_worker_state(
            account.id,
            "idle",
            phase="stopped"
        )

        raise

    except Exception as e:

        logger.exception(
            f"Worker failed for "
            f"{account.email}: {e}"
        )

        update_account_worker_state(
            account.id,
            "error",
            phase=phase,
            error=str(e)
        )
        phase = "error"

    finally:

        ACTIVE_BROWSER_RESOURCES.pop(
            account.id,
            None
        )

        if context:
            with suppress(Exception):
                await context.close()

        if browser:
            with suppress(Exception):
                await browser.close()

        if playwright:
            with suppress(Exception):
                await playwright.stop()

        if heartbeat_task:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

        logger.info(
            f"Worker stopped for "
            f"{account.email}"
        )

        current_task = asyncio.current_task()

        if ACTIVE_WORKERS.get(account.id) is current_task:
            ACTIVE_WORKERS.pop(account.id, None)

        if phase not in {"error", "proxy_error", "login_error"}:
            update_account_worker_state(
                account.id,
                "idle",
                phase=phase
            )


async def run_one_account_by_id(account_id):

    accounts = get_active_accounts()

    for account in accounts:

        if account.id == account_id:
            await run_account_worker(account)
            return

    logger.warning(
        f"Account {account_id} not found or inactive"
    )


def _forget_worker(account_id):

    def cleanup(task):

        if ACTIVE_WORKERS.get(account_id) is task:
            ACTIVE_WORKERS.pop(account_id, None)

        if task.cancelled():

            logger.info(
                f"Worker task for account "
                f"{account_id} cancelled"
            )

            return

        error = task.exception()

        if error:

            logger.error(
                f"Worker task for account "
                f"{account_id} ended with error: {error}"
            )

    return cleanup


# =========================================================
# REDIS / RQ BASED WORKER START
# =========================================================

async def start_account_worker(account_id):
    from app.workers.rq_worker import run_account_worker_sync

    if not is_operating_hours():
        logger.info("Outside operating hours")
        logger.info("Skipping worker cycle")
        update_account_worker_state(
            account_id,
            "idle",
            phase="outside_operating_hours",
        )
        return {
            "queued": False,
            "reason": "outside_operating_hours",
        }

    accounts = get_active_accounts()
    account = next(
        (candidate for candidate in accounts if candidate.id == account_id),
        None,
    )
    if not account:
        logger.info(f"Account {account_id} is not enabled. Skipping worker cycle.")
        update_account_worker_state(
            account_id,
            "idle",
            phase="not_enabled",
        )
        return {
            "queued": False,
            "reason": "not_enabled",
        }

    if _status_is_in_flight(account):
        logger.info(
            f"Account {account_id} already in flight. Skipping worker cycle."
        )
        return {
            "queued": False,
            "reason": "account_in_flight",
        }

    if is_account_on_cooldown(account_id):
        logger.info(f"Account {account_id} is cooling down. Skipping worker cycle.")
        return {
            "queued": False,
            "reason": "cooldown",
        }

    if not _proxy_is_healthy(account):
        logger.info(
            f"Account {account_id} proxy is not healthy. Skipping worker cycle."
        )
        return {
            "queued": False,
            "reason": "proxy_not_healthy",
        }

    for candidate in accounts:
        if candidate.id == account_id or candidate.proxy_id != account.proxy_id:
            continue
        if _status_is_in_flight(candidate):
            logger.info(f"Proxy busy, skipping account {account_id}")
            return {
                "queued": False,
                "reason": "proxy_busy",
            }

    logger.info(
        f"Queueing worker for account {account_id}"
    )

    update_account_worker_state(
        account_id,
        "queued",
        phase="queued"
    )

    job = worker_queue.enqueue(
        run_account_worker_sync,
        account_id,
        job_timeout="2h",
        retry=Retry(max=3, interval=[60, 300, 900]),
    )

    update_account_worker_state(
        account_id,
        "queued",
        phase="queued",
        job_id=job.id,
    )

    logger.info(
        f"RQ job {job.id} queued "
        f"for account {account_id}"
    )

    return {
        "queued": True,
        "job_id": job.id
    }


# =========================================================
# STOP WORKER
# =========================================================

async def stop_account_worker(account_id):

    logger.info(
        f"Stopping worker for account {account_id}"
    )

    update_account_worker_state(
        account_id,
        "stopping",
        phase="stopping"
    )

    resources = ACTIVE_BROWSER_RESOURCES.get(account_id) or {}

    browser = resources.get("browser")
    context = resources.get("context")
    playwright = resources.get("playwright")

    if context:
        with suppress(Exception):
            await context.close()

    if browser:
        with suppress(Exception):
            await browser.close()

    if playwright:
        with suppress(Exception):
            await playwright.stop()

    ACTIVE_WORKERS.pop(account_id, None)

    ACTIVE_BROWSER_RESOURCES.pop(account_id, None)

    update_account_worker_state(
        account_id,
        "idle",
        phase="stopped"
    )

    logger.info(
        f"Worker stopped for account {account_id}"
    )

    return True


def get_active_worker_count():

    return len([
        task
        for task in ACTIVE_WORKERS.values()
        if not task.done()
    ])
