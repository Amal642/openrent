from app.config import settings
from app.browser.launcher import save_cookies

async def login(page, context, account):

    await page.goto("https://www.openrent.co.uk/")

    # Check if Sign In button exists
    sign_in_btn = page.get_by_role("link", name="Sign In")

    if await sign_in_btn.count() == 0:
        print("Already logged in via saved session")
        return

    print("Logging in...")

    # Click sign in
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

    # Save cookies/session
    await save_cookies(context, account.session_file)

    print("Login successful")