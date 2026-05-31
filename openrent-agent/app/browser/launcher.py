from playwright.async_api import async_playwright
import os
import json


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
        slow_mo=500
    )

    context = await browser.new_context(proxy=proxy)

    # Load session cookies
    if account.session_file and os.path.exists(account.session_file):

        with open(account.session_file, "r") as f:
            cookies = json.load(f)

        await context.add_cookies(cookies)

    page = await context.new_page()

    return playwright, browser, context, page


async def save_cookies(context, session_file):

    cookies = await context.cookies()

    with open(session_file, "w") as f:
        json.dump(cookies, f, indent=2)