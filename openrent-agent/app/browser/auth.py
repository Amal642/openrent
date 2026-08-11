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


async def _dismiss_cookie_banner(page):
    """Best-effort dismissal of a cookie-consent overlay so it cannot cover the
    login form. Never raises — a missing banner is the normal case."""
    for name in ("Accept all", "Accept All", "Accept", "I Agree", "Allow all", "Got it"):
        try:
            btn = page.get_by_role("button", name=name)
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click(timeout=3000)
                logger.info(f"COOKIE_BANNER_DISMISSED via '{name}'")
                return
        except Exception:
            continue


async def _dismiss_account_picker(page):
    """Best-effort handling of the OpenID account-picker modal. When residual
    OpenID cookies survive into a fresh login, the provider renders a "Log in"
    modal listing a remembered account with a "Sign in to another account"
    option instead of the email form — which leaves the email field absent and
    breaks login with "Email field not found". Click that option so the email
    field renders. Never raises — an absent modal is the normal case."""
    for name in (
        "Sign in to another account",
        "Sign in with another account",
        "Use another account",
    ):
        try:
            getters = (
                page.get_by_role("button", name=name),
                page.get_by_role("link", name=name),
                page.get_by_text(name, exact=False),
            )
            for getter in getters:
                if await getter.count() > 0 and await getter.first.is_visible():
                    await getter.first.click(timeout=5000)
                    logger.info(f"LOGIN_ACCOUNT_PICKER_DISMISSED via '{name}'")
                    await page.wait_for_timeout(1000)
                    return
        except Exception:
            continue


async def _find_email_field(page):
    """Return the first VISIBLE email input, trying the primary Playwright role
    selector then Microsoft/OpenID fallbacks.

    Visibility matters: OpenRent's login page can hold a present-but-hidden email
    field (cookie overlay, mid-render, or a hidden responsive duplicate). Filling
    a present-but-hidden field blocks for the full 30s fill timeout, so we resolve
    to a visible element up front — waiting briefly for one to appear if needed.
    """
    candidates = [
        ("role:Enter email address", page.get_by_role("textbox", name="Enter email address")),
        ('input[name="loginfmt"]', page.locator('input[name="loginfmt"]')),
        ('input[name="openid-email"]', page.locator('input[name="openid-email"]')),
        ('input[type="email"]', page.locator('input[type="email"]')),
        ("#i0116", page.locator("#i0116")),
    ]

    # First pass: a candidate that is already visible.
    for label, loc in candidates:
        try:
            if await loc.count() > 0 and await loc.first.is_visible():
                logger.info(f"LOGIN_EMAIL_FIELD selector={label} state=visible")
                return loc.first
        except Exception:
            continue

    # Second pass: a present candidate — wait briefly for it to become visible
    # (fails fast at 10s instead of the 30s fill timeout if it never shows).
    for label, loc in candidates:
        try:
            if await loc.count() > 0:
                await loc.first.wait_for(state="visible", timeout=10000)
                logger.info(f"LOGIN_EMAIL_FIELD selector={label} state=waited_visible")
                return loc.first
        except Exception:
            continue

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

    # The stale session's cookies remain live in this context even after the
    # session file is deleted above. Those residual OpenID cookies make the
    # provider render an account-picker modal ("Sign in to another account")
    # instead of the email form, breaking fresh login with "Email field not
    # found". Clear cookies and reload so we get a clean login form.
    try:
        await context.clear_cookies()
        await page.goto("https://www.openrent.co.uk/", wait_until="domcontentloaded")
    except Exception as exc:
        logger.warning(
            f"Could not reset cookies before fresh login for {account.email}: {exc}"
        )

    sign_in_btn = page.get_by_role("link", name="Sign In")
    await sign_in_btn.click()

    # A cookie-consent overlay can cover the login form and leave the email
    # field present-but-hidden — dismiss it before locating the field.
    await _dismiss_cookie_banner(page)

    # If an OpenID account-picker modal still appears, choose "Sign in to another
    # account" so the email field renders instead of a remembered-account tile.
    await _dismiss_account_picker(page)

    email_field = await _find_email_field(page)
    if email_field is None:
        reason = "Email field not found — no matching selector after all fallbacks"
        await _capture_page_diagnostics(page, account.email, reason)
        _apply_login_failure(account.id, account.session_auth_failures, reason)
        raise RuntimeError(reason)

    try:
        # Generous fill timeout: under concurrent load on a small box the field
        # can take several seconds to become actionable even once visible.
        await email_field.fill(account.email, timeout=25000)

        await page.get_by_role("button", name="Continue with email").click()
        slug = account.email.split("@")[0].replace(".", "_")
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshots_dir / f"post_email_{slug}.png"), full_page=True)
        logger.info(
            f"LOGIN_AFTER_EMAIL_STEP email={account.email} "
            f"url={page.url} title={await page.title()!r}"
        )

        # Wait for the password step to render after "Continue with email"
        # before filling — the transition can lag under load, and filling too
        # early raced it into a timeout.
        password_field = page.locator('input[name="password"]')
        await password_field.wait_for(state="visible", timeout=25000)
        await password_field.fill(account.password, timeout=25000)

        await page.get_by_role("button", name="Log in").click()
        # OpenRent's modal login runs an async OpenID redirect that takes
        # ~3-4s to complete and set the session cookie. A fixed 3s wait races
        # that redirect: if we check auth too early, the cookie isn't set yet
        # and the login is falsely seen as failed. Wait for the actual
        # post-login navigation instead, falling back to a fixed delay.
        try:
            await page.wait_for_url("**/my-dashboard**", timeout=15000)
            logger.info(f"LOGIN_REDIRECT_OK email={account.email} url={page.url}")
        except Exception:
            logger.info(
                f"LOGIN_REDIRECT_TIMEOUT email={account.email} url={page.url} "
                "— falling back to fixed wait"
            )
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
