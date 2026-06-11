import os
from pathlib import Path

from app.browser.launcher import get_session_file, save_storage_state
from app.db.repository import update_session_health
from app.utils.logger import logger

# Backoff cooldown minutes per failure index (1-indexed)
_LOGIN_FAIL_COOLDOWN = {1: 10, 2: 20, 3: 30, 4: 30}
LOGIN_FAIL_PERMANENT_THRESHOLD = 5


async def _is_authenticated(page):
    await page.goto("https://www.openrent.co.uk/", wait_until="domcontentloaded")
    sign_in_btn = page.get_by_role("link", name="Sign In")
    return await sign_in_btn.count() == 0


async def _captcha_suspected(page):
    content = (await page.content()).lower()
    return "captcha" in content or "verify you are human" in content


async def _capture_page_diagnostics(page, email: str, reason: str):
    """Log URL, title, HTML snippet and save screenshot on login failure."""
    try:
        url = page.url
        title = await page.title()
        content = await page.content()
        html_snippet = content[:3000]
        logger.info(
            f"LOGIN_PAGE_URL email={email} url={url}\n"
            f"LOGIN_PAGE_TITLE email={email} title={title}\n"
            f"LOGIN_FAILURE_REASON email={email} reason={reason}\n"
            f"LOGIN_PAGE_HTML_SNIPPET:\n{html_snippet}"
        )
    except Exception as exc:
        logger.warning(f"Could not capture page text diagnostics for {email}: {exc}")

    try:
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        slug = email.split("@")[0].replace(".", "_")
        screenshot_path = str(screenshots_dir / f"login_fail_{slug}.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        logger.info(f"LOGIN_FAILURE_SCREENSHOT saved to {screenshot_path}")
    except Exception as exc:
        logger.warning(f"Could not save login failure screenshot for {email}: {exc}")


async def _find_email_field(page):
    """Try the primary Playwright role selector then Microsoft login fallbacks."""
    primary = page.get_by_role("textbox", name="Enter email address")
    if await primary.count() > 0:
        return primary
    for selector in ['input[name="loginfmt"]', 'input[type="email"]', "#i0116"]:
        fallback = page.locator(selector)
        if await fallback.count() > 0:
            logger.info(f"LOGIN_EMAIL_FIELD_FALLBACK selector={selector}")
            return fallback
    return None


def _apply_login_failure(account_id: int, current_failures: int, reason: str):
    """Record a login failure, increment counter, and set an appropriate cooldown."""
    failures = (current_failures or 0) + 1
    if failures >= LOGIN_FAIL_PERMANENT_THRESHOLD:
        logger.warning(
            f"LOGIN_FAIL_THRESHOLD_REACHED account_id={account_id} "
            f"failures={failures} — marking login_failed with 24h cooldown"
        )
        update_session_health(
            account_id,
            "login_failed",
            error=reason,
            cooldown_minutes=1440,  # 24 hours — blocks scheduler until manual reset
        )
    else:
        cooldown_min = _LOGIN_FAIL_COOLDOWN.get(failures, 30)
        logger.warning(
            f"LOGIN_FAIL account_id={account_id} "
            f"failures={failures} cooldown={cooldown_min}m reason={reason}"
        )
        update_session_health(
            account_id,
            "login_failed",
            error=reason,
            cooldown_minutes=cooldown_min,
        )


async def login(page, context, account):
    session_file = get_session_file(account)

    if await _is_authenticated(page):
        update_session_health(account.id, "active")
        return

    # Session file exists but we're not authenticated → stale or corrupted
    if session_file and os.path.exists(session_file):
        logger.info(
            f"LOGIN_STALE_SESSION email={account.email} "
            f"session_file={session_file} — deleting for fresh login"
        )
        try:
            os.remove(session_file)
        except OSError as exc:
            logger.warning(f"Could not delete stale session file {session_file}: {exc}")

    update_session_health(account.id, "logging_in")

    sign_in_btn = page.get_by_role("link", name="Sign In")
    await sign_in_btn.click()

    email_field = await _find_email_field(page)
    if email_field is None:
        reason = "Email field not found — no matching selector after all fallbacks"
        await _capture_page_diagnostics(page, account.email, reason)
        _apply_login_failure(account.id, account.session_auth_failures, reason)
        raise RuntimeError(reason)

    try:
        await email_field.fill(account.email)

        await page.get_by_role("button", name="Continue with email").click()
        slug = account.email.split("@")[0].replace(".", "_")
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshots_dir / f"post_email_{slug}.png"), full_page=True)
        logger.info(
            f"LOGIN_AFTER_EMAIL_STEP email={account.email} "
            f"url={page.url} title={await page.title()!r}"
        )

        await page.locator('input[name="password"]').fill(account.password)

        await page.get_by_role("button", name="Log in").click()
        await page.wait_for_timeout(3000)

    except Exception as exc:
        reason = str(exc)
        await _capture_page_diagnostics(page, account.email, reason)
        _apply_login_failure(account.id, account.session_auth_failures, reason)
        raise

    # Capture the page state immediately after login attempt — before
    # _is_authenticated() navigates to the homepage and destroys this state.
    # This screenshot shows any error message, verification step, or captcha.
    try:
        post_login_url = page.url
        post_login_title = await page.title()
        post_login_content = await page.content()
        post_login_snippet = post_login_content[:3000]
        slug = account.email.split("@")[0].replace(".", "_")
        await page.screenshot(
            path=str(Path("screenshots") / f"post_login_{slug}.png"), full_page=True
        )
        logger.info(
            f"POST_LOGIN_STATE email={account.email} "
            f"url={post_login_url} title={post_login_title!r}"
        )
        # Detect visible error text on the login page
        error_keywords = [
            "incorrect password", "invalid password", "wrong password",
            "invalid email", "account not found", "too many", "locked",
            "suspended", "verify", "verification", "captcha", "security",
        ]
        page_text_lower = post_login_content.lower()
        detected_errors = [kw for kw in error_keywords if kw in page_text_lower]
        if detected_errors:
            logger.warning(
                f"LOGIN_ERROR_KEYWORDS_DETECTED email={account.email} "
                f"keywords={detected_errors}"
            )
        logger.info(f"POST_LOGIN_HTML_SNIPPET email={account.email}:\n{post_login_snippet}")
    except Exception as diag_exc:
        logger.warning(f"Could not capture post-login diagnostics for {account.email}: {diag_exc}")

    if await _captcha_suspected(page):
        update_session_health(
            account.id,
            "captcha_suspected",
            error="Captcha suspected during login",
            captcha_triggered=True,
        )
        raise RuntimeError("Captcha suspected during login")

    if not await _is_authenticated(page):
        reason = "Login completed but authenticated state was not detected"
        await _capture_page_diagnostics(page, account.email, reason)
        _apply_login_failure(account.id, account.session_auth_failures, reason)
        raise RuntimeError(reason)

    await save_storage_state(context, session_file)
    update_session_health(account.id, "active", login_success=True)
