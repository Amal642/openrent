from app.browser.launcher import get_session_file, save_storage_state
from app.db.repository import update_session_health


async def _is_authenticated(page):
    await page.goto("https://www.openrent.co.uk/", wait_until="domcontentloaded")
    sign_in_btn = page.get_by_role("link", name="Sign In")
    return await sign_in_btn.count() == 0


async def _captcha_suspected(page):
    content = (await page.content()).lower()
    return "captcha" in content or "verify you are human" in content

async def login(page, context, account):

    session_file = get_session_file(account)
    if await _is_authenticated(page):
        update_session_health(account.id, "active")
        return

    update_session_health(account.id, "logging_in")

    sign_in_btn = page.get_by_role("link", name="Sign In")
    await sign_in_btn.click()

    # Fill email
    await page.get_by_role(
        "textbox",
        name="Enter email address"
    ).fill(account.email)

    # Continue
    await page.get_by_role(
        "button",
        name="Continue with email"
    ).click()
    await page.screenshot(
        path="login-debug.png",
        full_page=True
    )

    # Fill password
    await page.get_by_role(
        "textbox",
        name="Enter password"
    ).fill(account.password)

    # Login
    await page.get_by_role(
        "button",
        name="Log in"
    ).click()

    await page.wait_for_timeout(3000)

    if await _captcha_suspected(page):
        update_session_health(
            account.id,
            "captcha_suspected",
            error="Captcha suspected during login",
            captcha_triggered=True,
        )
        raise RuntimeError("Captcha suspected during login")

    if not await _is_authenticated(page):
        update_session_health(
            account.id,
            "login_failed",
            error="Login completed but authenticated state was not detected",
        )
        raise RuntimeError("Login failed: authenticated state was not detected")

    await save_storage_state(context, session_file)
    update_session_health(account.id, "active", login_success=True)
