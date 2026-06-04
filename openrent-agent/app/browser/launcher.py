from playwright.async_api import async_playwright
import os
import json
from pathlib import Path


def get_session_file(account):
    configured = (account.session_file or "").strip()
    if configured and configured != "session.json":
        return configured

    sessions_dir = Path("sessions")
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return str(sessions_dir / f"account_{account.id}.json")


def _proxy_config_for_account(account) -> dict | None:
    """
    Resolve proxy credentials: prefer the linked Proxy record (proxy_id),
    fall back to legacy direct fields (proxy_server).
    """
    linked = getattr(account, "proxy", None)
    if linked and linked.is_active and linked.host:
        server = f"http://{linked.host}:{linked.port}"
        return {
            "server": server,
            "username": linked.username or "",
            "password": linked.password or "",
        }
    if account.proxy_server:
        return {
            "server": account.proxy_server,
            "username": account.proxy_username or "",
            "password": account.proxy_password or "",
        }
    return None


async def launch_browser(account):

    playwright = await async_playwright().start()

    proxy = _proxy_config_for_account(account)

    browser = await playwright.chromium.launch()

    session_file = get_session_file(account)
    context_kwargs = {
        "ignore_https_errors": True,
    }

    if proxy:
        context_kwargs["proxy"] = proxy

    if session_file and os.path.exists(session_file):

        with open(session_file, "r") as f:
            session_data = json.load(f)

        if isinstance(session_data, dict):
            context_kwargs["storage_state"] = session_file

    context = await browser.new_context(**context_kwargs)

    # Backward compatibility for legacy cookie-only session files.
    if session_file and os.path.exists(session_file):
        with open(session_file, "r") as f:
            session_data = json.load(f)

        if isinstance(session_data, list):
            await context.add_cookies(session_data)

    page = await context.new_page()

    return playwright, browser, context, page


async def save_cookies(context, session_file):

    cookies = await context.cookies()

    with open(session_file, "w") as f:
        json.dump(cookies, f, indent=2)


async def save_storage_state(context, session_file):
    Path(session_file).parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=session_file)
