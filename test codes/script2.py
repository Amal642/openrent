from playwright.sync_api import sync_playwright
import time, json, re

LOGIN = "https://www.openrent.co.uk/login"
INBOX = "https://www.openrent.co.uk/messages"

def wait_for_new_thread(page):
    """Return dict {thread_id: last_msg_text} that arrived after last check."""
    page.goto(INBOX)
    threads = page.locator(".message-thread").all()
    new = {}
    for t in threads:
        thread_id = t.get_attribute("data-thread-id")
        last_text = t.locator(".last-message").inner_text()
        if thread_id not in seen_threads:
            new[thread_id] = last_text
    return new
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(LOGIN)

    page.fill('input[name="email"]', "your_email@example.com")
    page.fill('input[name="password"]', "your_password")
    page.click('button[type="submit"]')
