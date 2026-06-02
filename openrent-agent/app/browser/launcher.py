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


async def launch_browser(account):

    playwright = await async_playwright().start()

    proxy = None

    # Load proxy if account has one
    if account.proxy_server:
        proxy = {
            "server": account.proxy_server,
            "username": account.proxy_username,
            "password": account.proxy_password
        }

    browser = await playwright.chromium.launch(
        headless=True,
        slow_mo=500,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    session_file = get_session_file(account)
    context_kwargs = {"proxy": proxy} if proxy else {}

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
