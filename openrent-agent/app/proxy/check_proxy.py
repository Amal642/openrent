from __future__ import annotations

import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


IP_CHECK_URL = "https://api.ipify.org"
OPENRENT_URL = "https://www.openrent.co.uk"
DEFAULT_TIMEOUT_SECONDS = 15
SLOW_LATENCY_SECONDS = 8


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


def check_proxy(proxy_url: str) -> dict:
    """Validate HTTPS connectivity, egress IP, OpenRent access, and latency."""
    if not proxy_url:
        return {
            "healthy": False,
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
        )
    )

    try:
        ip, ip_status = _fetch_through_proxy(
            opener,
            IP_CHECK_URL,
            DEFAULT_TIMEOUT_SECONDS,
        )
        _, openrent_status = _fetch_through_proxy(
            opener,
            OPENRENT_URL,
            DEFAULT_TIMEOUT_SECONDS,
            method="HEAD",
        )
        latency = round(time.perf_counter() - started, 3)

        if openrent_status >= 400:
            return {
                "healthy": False,
                "ip": ip,
                "latency": latency,
                "status_code": openrent_status,
                "error": f"OpenRent returned HTTP {openrent_status}",
            }

        return {
            "healthy": latency <= SLOW_LATENCY_SECONDS,
            "ip": ip,
            "latency": latency,
            "status_code": openrent_status or ip_status,
            **(
                {"error": f"Proxy is slow: {latency}s"}
                if latency > SLOW_LATENCY_SECONDS
                else {}
            ),
        }

    except HTTPError as exc:
        return {
            "healthy": False,
            "status_code": exc.code,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except URLError as exc:
        return {
            "healthy": False,
            "error": str(exc.reason),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "error": str(exc),
        }
