"""
One-off script: update the OpenRent profile display name for account 17
from "Alex" to "Louise" to match the DB persona_name.

Run from the openrent-agent/ directory:
    python -m scripts.update_openrent_display_name
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import joinedload
from app.browser.launcher import launch_browser, save_storage_state, get_session_file
from app.browser.auth import _is_authenticated
from app.db.models import Account
from app.db.repository import session_scope
from app.utils.logger import logger


def load_account_with_proxy(account_id):
    with session_scope() as db:
        return (
            db.query(Account)
            .options(joinedload(Account.proxy))
            .filter(Account.id == account_id)
            .first()
        )

ACCOUNT_ID = 17
NEW_FIRST_NAME = "Louise"
EDIT_URL = "https://www.openrent.co.uk/account/edit"


async def find_settings_page(page):
    logger.info(f"Navigating to {EDIT_URL}")
    await page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)
    el = page.locator('input[name="FirstName"]').first
    if await el.count() > 0:
        logger.info(f"Found FirstName field at {EDIT_URL}")
        return True
    logger.error("FirstName field not found on /account/edit")
    return False


async def update_name(page, new_name):
    el = page.locator('input[name="FirstName"]').first
    if await el.count() > 0:
        current = await el.input_value()
        logger.info(f"Current FirstName value: '{current}'")
        await el.click(click_count=3)
        await el.fill(new_name)
        logger.info(f"Filled '{new_name}' into FirstName field")
        return 'input[name="FirstName"]'
    logger.warning("No FirstName input found — dumping all inputs")
    inputs = await page.locator("input").all()
    for i, inp in enumerate(inputs):
        try:
            name_attr = await inp.get_attribute("name") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            val = await inp.input_value()
            logger.info(f"  Input {i}: name={name_attr!r} placeholder={placeholder!r} value={val!r}")
        except Exception:
            pass
    return None


async def save_form(page):
    # Target the visible Save button in the edit form, not the hidden login overlay buttons
    btn = page.locator('button[type="submit"]:visible:has-text("Save")').first
    if await btn.count() > 0:
        await btn.click()
        await page.wait_for_timeout(2000)
        logger.info("Clicked Save button")
        return True
    logger.warning("No visible Save button found")
    return False


async def main():
    account = load_account_with_proxy(ACCOUNT_ID)
    if not account:
        logger.error(f"Account {ACCOUNT_ID} not found")
        return

    logger.info(f"Updating display name for account {ACCOUNT_ID} ({account.email}) → '{NEW_FIRST_NAME}'")
    logger.info(f"Using proxy: {getattr(account.proxy, 'host', 'none')}:{getattr(account.proxy, 'port', '')}")

    playwright, browser, context, page = await launch_browser(account)

    try:
        if not await _is_authenticated(page):
            logger.error("Account is not authenticated — session may be expired. Run login first.")
            return

        logger.info("Session is active, proceeding to profile settings")

        found = await find_settings_page(page)
        if not found:
            logger.error("Could not find profile settings page")
            await page.screenshot(path="/tmp/settings_not_found.png", full_page=True)
            logger.info("Screenshot saved to /tmp/settings_not_found.png")
            return

        await page.screenshot(path="/tmp/settings_before.png", full_page=True)
        logger.info("Screenshot before: /tmp/settings_before.png")

        field = await update_name(page, NEW_FIRST_NAME)
        if not field:
            logger.error("Could not find name field — manual intervention needed")
            return

        saved = await save_form(page)
        await page.wait_for_timeout(2000)

        await page.screenshot(path="/tmp/settings_after.png", full_page=True)
        logger.info("Screenshot after: /tmp/settings_after.png")

        session_file = get_session_file(account)
        await save_storage_state(context, session_file)
        logger.info(f"Session saved to {session_file}")

        if saved:
            logger.info(f"SUCCESS: display name updated to '{NEW_FIRST_NAME}' for account {ACCOUNT_ID}")
        else:
            logger.warning("Form may not have saved — check screenshots")

    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
