
    # browser = playwright.chromium.launch(headless=False)
    # context = browser.new_context()
    # page = context.new_page()
    # page.goto("https://www.openrent.co.uk/")
    # page.get_by_role("link", name="Sign In").click()
    # page.get_by_role("textbox", name="Enter email address").click()
    # page.get_by_role("textbox", name="Enter email address").fill("mary.sinclair98@hotmail.com")
    # page.get_by_role("button", name="Continue with email").click()
    # page.get_by_role("textbox", name="Enter password").fill("marysinclair98")
    # page.get_by_role("button", name="Log in").click()
    # page.get_by_role("link", name="Bed Flat, Norfolk House, SW1P").click()
    # page.get_by_role("link", name="Message Landlord or Request").click()
    # page.get_by_role("button", name="Request Viewing").click()
    # page.get_by_role("link", name="OK", exact=True).click()
    # page.get_by_role("button", name="Close").click()


import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.openrent.co.uk/")
    page.get_by_role("link", name="Sign In").click()
    page.get_by_role("textbox", name="Enter email address").click()
    page.get_by_role("textbox", name="Enter email address").fill("mary.sinclair@hotmail.com")
    page.get_by_role("textbox", name="Enter email address").press("Enter")
    page.get_by_role("button", name="Continue with email").click()
    page.locator("input[name=\"Email\"]").click()
    page.get_by_role("link", name="← Back").click()
    page.get_by_role("textbox", name="Enter email address").click()
    page.get_by_role("textbox", name="Enter email address").click()
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").press("ArrowLeft")
    page.get_by_role("textbox", name="Enter email address").fill("mary.sinclair98@hotmail.com")
    page.get_by_role("button", name="Continue with email").click()
    page.get_by_role("textbox", name="Enter password").fill("marysinclair98")
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("link", name="Room in a Shared House, Osmaston Road, DE24").click()
    page.get_by_role("link", name="Message Landlord or Request").click()
    page.goto("https://www.openrent.co.uk/")
    page.get_by_role("link", name="Bed Flat, Montreal Road, CB1").click()
    page.get_by_role("link", name="Message Landlord or Request").click()
    page.get_by_role("textbox", name="Message").click()
    page.get_by_role("textbox", name="Message").click()
    page.get_by_role("textbox", name="Message").fill("Hi, I’m Mary. My husband and I are interested in the property you have listed. We would truly appreciate it if you could share your contact details, as we’d like to have a brief conversation before confirming a viewing.\nWe hope to hear back from you soon.\nThank you")

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)

