async def login(page, email, password):
    await page.goto("https://www.openrent.co.uk/")
    await page.get_by_role("link", name="Sign In").click()

    await page.get_by_role("textbox", name="Enter email address").fill(email)
    await page.get_by_role("button", name="Continue with email").click()

    await page.get_by_role("textbox", name="Enter password").fill(password)
    await page.get_by_role("button", name="Log in").click()

    await page.wait_for_timeout(2000)