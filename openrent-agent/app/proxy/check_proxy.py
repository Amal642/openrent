from __future__ import annotations

import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


IP_CHECK_URL = "https://api.ipify.org"
OPENRENT_URL = "https://www.openrent.co.uk"
DEFAULT_TIMEOUT_SECONDS = 5
DEGRADED_LATENCY_SECONDS = 2
SLOW_LATENCY_SECONDS = 4


def _fetch_through_proxy(opener, url: str, timeout: int, method: str = "GET") -> tuple[str, int]:
    request = Request(
        url,
        method=method,
        headers={
            "User-Agent": (
                "Mozilla/5.0 OpenRentAutomation/1.0 "
                "(proxy-health-check)"
            )
        },
    )
    with opener.open(request, timeout=timeout) as response:
        body = response.read(4096).decode("utf-8", errors="ignore").strip()
        return body, int(response.status)


def _latency_status(latency: float) -> str:
    if latency >= SLOW_LATENCY_SECONDS:
        return "slow"
    if latency >= DEGRADED_LATENCY_SECONDS:
        return "degraded"
    return "ok"


def check_proxy(proxy_url: str) -> dict:
    """
    Validate HTTPS connectivity, egress IP, OpenRent reachability, and latency.

    Both requests (ipify + OpenRent HEAD) run concurrently so wall-time latency
    equals max(T_ipify, T_openrent) rather than their sum.

    Timeout: 5s per request (was 15s).

    Returns status: "ok" (<2s) | "degraded" (2-4s) | "slow" (4-5s) | "down" (error/timeout)
    healthy=True for ok/degraded/slow; healthy=False for down.
    """
    if not proxy_url:
        return {
            "healthy": False,
            "status": "down",
            "error": "Proxy URL is empty",
        }

    started = time.perf_counter()
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        ProxyHandler(
            {
                "http": proxy_url,
                "https": proxy_url,
            }
        ),
    )

    ip = None
    ip_error = None
    openrent_status_code = None
    openrent_error = None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_ip = pool.submit(
                _fetch_through_proxy,
                opener, IP_CHECK_URL, DEFAULT_TIMEOUT_SECONDS,
            )
            future_or = pool.submit(
                _fetch_through_proxy,
                opener, OPENRENT_URL, DEFAULT_TIMEOUT_SECONDS, "HEAD",
            )

            try:
                ip, _ = future_ip.result(timeout=DEFAULT_TIMEOUT_SECONDS + 1)
            except Exception as exc:
                ip_error = str(exc)

            try:
                _, openrent_status_code = future_or.result(
                    timeout=DEFAULT_TIMEOUT_SECONDS + 1
                )
            except Exception as exc:
                openrent_error = str(exc)

        latency = round(time.perf_counter() - started, 3)

        if not ip:
            return {
                "healthy": False,
                "status": "down",
                "latency": latency,
                "error": ip_error or "Could not retrieve egress IP through proxy",
            }

        if openrent_status_code is not None and openrent_status_code >= 400:
            return {
                "healthy": False,
                "status": "down",
                "ip": ip,
                "latency": latency,
                "status_code": openrent_status_code,
                "error": f"OpenRent returned HTTP {openrent_status_code}",
            }

        status = _latency_status(latency)
        result: dict = {
            "healthy": True,
            "status": status,
            "ip": ip,
            "latency": latency,
            "status_code": openrent_status_code,
        }
        if openrent_error:
            result["error"] = f"OpenRent unreachable: {openrent_error}"
        return result

    except HTTPError as exc:
        return {
            "healthy": False,
            "status": "down",
            "status_code": exc.code,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except URLError as exc:
        return {
            "healthy": False,
            "status": "down",
            "error": str(exc.reason),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "status": "down",
            "error": str(exc),
        }
