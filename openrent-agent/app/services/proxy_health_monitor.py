import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit

from app.utils.logger import logger

RETRY_INTERVALS_MINUTES = [1, 2, 4, 5, 10, 15, 30]
UNHEALTHY_PROXY_STATUSES = {"down", "failed"}
UNHEALTHY_WORKER_STATUSES = {"proxy_error"}
MONITOR_POLL_INTERVAL_SECONDS = 60

# After this many consecutive failed health checks on the same proxy, stop
# retrying it and reassign every account on it to a healthy spare instead.
REASSIGN_AFTER_FAILURES = 3

# in-memory: proxy_key → {failures: int, next_check_at: datetime}
_proxy_retry_state: dict[str, dict] = {}


def _proxy_key(account) -> str | None:
    if getattr(account, "proxy_id", None):
        return f"proxy:{account.proxy_id}"
    proxy_server = getattr(account, "proxy_server", None)
    if proxy_server:
        return f"server:{proxy_server}"
    return None


def _proxy_url(account) -> str | None:
    linked = getattr(account, "proxy", None)
    if linked and linked.is_active and linked.host:
        server = f"http://{linked.host}:{linked.port}"
        if not linked.username:
            return server
        username = quote(linked.username, safe="")
        password = quote(linked.password or "", safe="")
        return f"http://{username}:{password}@{linked.host}:{linked.port}"

    proxy_server = (getattr(account, "proxy_server", None) or "").strip()
    if not proxy_server:
        return None

    parsed = urlsplit(
        proxy_server if "://" in proxy_server else f"http://{proxy_server}"
    )
    if not getattr(account, "proxy_username", None):
        return urlunsplit(parsed)

    username = quote(account.proxy_username, safe="")
    password = quote(account.proxy_password or "", safe="")
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
    return urlunsplit(
        (parsed.scheme, f"{username}:{password}@{netloc}", parsed.path, parsed.query, parsed.fragment)
    )


def _account_is_proxy_unhealthy(account) -> bool:
    proxy_status = str(getattr(account, "proxy_status", "") or "").lower()
    worker_status = str(getattr(account, "worker_status", "") or "").lower()
    return (
        proxy_status in UNHEALTHY_PROXY_STATUSES
        or worker_status in UNHEALTHY_WORKER_STATUSES
    )


async def _run_monitor_cycle():
    from app.proxy.check_proxy import check_proxy
    from app.db.repository import get_active_accounts, update_proxy_health, update_account_worker_state

    now = datetime.utcnow()
    accounts = get_active_accounts()

    # Map proxy_key → representative account (first unhealthy one found per proxy)
    unhealthy_by_proxy: dict[str, object] = {}
    for account in accounts:
        if not _account_is_proxy_unhealthy(account):
            continue
        key = _proxy_key(account)
        if key and key not in unhealthy_by_proxy:
            unhealthy_by_proxy[key] = account

    # Mark newly-detected unhealthy proxies
    for key, account in unhealthy_by_proxy.items():
        if key not in _proxy_retry_state:
            next_check = now + timedelta(minutes=RETRY_INTERVALS_MINUTES[0])
            _proxy_retry_state[key] = {"failures": 0, "next_check_at": next_check}
            logger.warning(
                f"PROXY_MARKED_UNHEALTHY proxy_key={key} "
                f"account_id={account.id} "
                f"next_check={next_check.strftime('%H:%M:%S')}"
            )

    # Purge state for proxies that are no longer unhealthy (recovered outside of monitor)
    stale_keys = [k for k in list(_proxy_retry_state.keys()) if k not in unhealthy_by_proxy]
    for key in stale_keys:
        _proxy_retry_state.pop(key, None)

    # Run health checks on proxies that are due
    for key, state in list(_proxy_retry_state.items()):
        if now < state["next_check_at"]:
            continue

        account = unhealthy_by_proxy.get(key)
        if not account:
            _proxy_retry_state.pop(key, None)
            continue

        proxy_url = _proxy_url(account)
        if not proxy_url:
            _proxy_retry_state.pop(key, None)
            continue

        logger.info(
            f"PROXY_RETRY proxy_key={key} "
            f"account_id={account.id} "
            f"attempt={state['failures'] + 1}"
        )

        result = await asyncio.to_thread(check_proxy, proxy_url)
        update_proxy_health(account.id, result)

        if result.get("healthy"):
            logger.info(
                f"PROXY_RECOVERED proxy_key={key} "
                f"latency={result.get('latency')}s"
            )
            _proxy_retry_state.pop(key, None)

            # Reset and re-queue all accounts on this proxy
            for candidate in accounts:
                if _proxy_key(candidate) != key:
                    continue
                from app.db.repository import reset_failed_listings_for_account
                reset_failed_listings_for_account(candidate.id)
                logger.info(f"LISTINGS_RESET account_id={candidate.id} reason=proxy_recovered")
                worker_status = str(getattr(candidate, "worker_status", "") or "").lower()
                if worker_status in UNHEALTHY_WORKER_STATUSES:
                    update_account_worker_state(candidate.id, "idle", phase="proxy_recovered")
                    logger.info(f"ACCOUNT_REQUEUED account_id={candidate.id} reason=proxy_recovered")
                    from app.workers.account_worker import start_account_worker
                    await start_account_worker(candidate.id)
        else:
            failures = state["failures"] + 1

            if failures >= REASSIGN_AFTER_FAILURES:
                from app.db.repository import reassign_account_proxy

                logger.warning(
                    f"PROXY_REASSIGN_TRIGGERED proxy_key={key} "
                    f"failures={failures} error={result.get('error', '')}"
                )
                _proxy_retry_state.pop(key, None)

                for candidate in accounts:
                    if _proxy_key(candidate) != key:
                        continue
                    outcome = reassign_account_proxy(
                        candidate.id, reason="proxy_unhealthy_3_retries"
                    )
                    if outcome.get("reassigned"):
                        from app.db.repository import reset_failed_listings_for_account
                        reset_failed_listings_for_account(candidate.id)
                        logger.info(f"LISTINGS_RESET account_id={candidate.id} reason=proxy_reassigned")
                        update_account_worker_state(
                            candidate.id, "idle", phase="proxy_reassigned"
                        )
                        from app.workers.account_worker import start_account_worker
                        await start_account_worker(candidate.id)
                    else:
                        logger.error(
                            f"PROXY_REASSIGN_FAILED account_id={candidate.id} "
                            f"reason={outcome.get('reason')}"
                        )
                continue

            interval_idx = min(failures, len(RETRY_INTERVALS_MINUTES) - 1)
            next_check = now + timedelta(minutes=RETRY_INTERVALS_MINUTES[interval_idx])
            _proxy_retry_state[key] = {"failures": failures, "next_check_at": next_check}
            logger.warning(
                f"PROXY_STILL_UNHEALTHY proxy_key={key} "
                f"failures={failures} "
                f"next_check_in={RETRY_INTERVALS_MINUTES[interval_idx]}m "
                f"error={result.get('error', '')}"
            )


async def proxy_health_monitor_loop():
    while True:
        try:
            await _run_monitor_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Proxy health monitor cycle failed: {exc}")
        await asyncio.sleep(MONITOR_POLL_INTERVAL_SECONDS)


def start_proxy_health_monitor():
    return asyncio.create_task(proxy_health_monitor_loop(), name="proxy-health-monitor")


async def stop_proxy_health_monitor(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def prewarm_proxy_health():
    """
    Check all active proxies concurrently at startup so the 20-minute health
    cache is populated before the scheduler dispatches the first worker cycle.

    Deduplicates by proxy key — one check per physical proxy, not per account.
    Max 5 concurrent checks (each takes up to 5s, so ~5s total wall time for
    up to 5 proxies, ~10s for up to 10, etc.).
    """
    from app.proxy.check_proxy import check_proxy
    from app.db.repository import get_active_accounts, update_proxy_health

    accounts = get_active_accounts()

    seen_keys: set[str] = set()
    to_check: list[tuple[object, str]] = []
    for account in accounts:
        key = _proxy_key(account)
        url = _proxy_url(account)
        if key and url and key not in seen_keys:
            seen_keys.add(key)
            to_check.append((account, url))

    if not to_check:
        logger.info("PROXY_PREWARM_SKIP reason=no_active_proxies")
        return

    logger.info(f"PROXY_PREWARM_START proxies={len(to_check)}")
    semaphore = asyncio.Semaphore(5)

    async def _check_one(account, url: str):
        async with semaphore:
            try:
                result = await asyncio.to_thread(check_proxy, url)
                update_proxy_health(account.id, result)
                logger.info(
                    f"PROXY_PREWARM_RESULT "
                    f"account_id={account.id} "
                    f"status={result.get('status')} "
                    f"latency={result.get('latency')}s"
                )
            except Exception as exc:
                logger.warning(
                    f"PROXY_PREWARM_ERROR account_id={account.id} error={exc}"
                )

    await asyncio.gather(*[_check_one(acc, url) for acc, url in to_check])
    logger.info("PROXY_PREWARM_COMPLETE")


def start_proxy_prewarm():
    return asyncio.create_task(prewarm_proxy_health(), name="proxy-prewarm")
