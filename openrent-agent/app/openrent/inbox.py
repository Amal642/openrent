import math
from app.utils.text import strip_ai_dashes

from app.openrent.popups import close_verified_tenant_popup
from app.services import page_health
from app.utils.human import random_sleep
from app.utils.logger import logger
import re
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://www.openrent.co.uk/myenquiries"

# Our own messages carry this class on the thread page. Every thread is one we
# started, so a thread with no marked message means the page changed under us.
OWN_MESSAGE_CLASS = "current-user"
_THREAD_URL_RE = re.compile(r"/messages/(\d+)")
# Below this many letters/digits a text match could be a coincidence ("ok").
_MIN_MATCH_CHARS = 20


class SenderDetectionError(Exception):
    """The thread page no longer marks which messages are ours. Acting on it
    would treat our own last message as the landlord's and reply to ourselves,
    so the thread is skipped until the selector is fixed."""


def _match_key(text):
    """Text reduced to letters and digits, with phone numbers and OpenRent's
    "(Number Removed)" collapsed, so a message we stored compares equal to how
    the page shows it (dashes stripped at send, numbers redacted, whitespace)."""
    keyed = re.sub(r"\(number removed\)|\+?\d[\d \-]{6,}\d", "#", (text or "").lower())
    return re.sub(r"[^a-z0-9#]", "", keyed)


def _thread_id_from_url(url):
    match = _THREAD_URL_RE.search(url or "")
    return match.group(1) if match else None


def _stored_outbound_keys(thread_id):
    if not thread_id:
        return []
    try:
        from app.db.repository import get_outbound_message_texts

        keys = [_match_key(t) for t in get_outbound_message_texts(thread_id)]
    except Exception as exc:
        logger.warning(f"OUTBOUND_TEXTS_LOOKUP_FAILED thread_id={thread_id} error={exc}")
        return []
    return [k for k in keys if len(k) >= _MIN_MATCH_CHARS]


def is_our_stored_message(text, stored_keys):
    key = _match_key(text)
    if len(key) < _MIN_MATCH_CHARS:
        return False
    return any(k == key or k in key or key in k for k in stored_keys)


async def open_inbox_page(page, start=0):

    url = f"{BASE_URL}?Start={start}"

    print(f"\nOpening inbox page: {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_load_state("load")


async def get_total_pages(page):

    try:

        paragraphs = await page.query_selector_all("p")

        for p in paragraphs:

            text = await p.inner_text()

            text = text.strip()

            print("Paragraph text:", text)

            # Example:
            # Page:
            # 6 / 7

            if "Page:" in text and "/" in text:

                parts = text.split("/")

                total = parts[-1].strip()

                return int(total)

        return 1

    except Exception as e:

        print("Could not detect total pages:", e)

        return 1

async def extract_reply_threads(page, record_health=False):

    cards = await page.query_selector_all(
        "div[id^='thread-']"
    )

    results = []
    previews_found = 0

    print(f"Found {len(cards)} thread cards")

    for card in cards:

        try:

            thread_id = await card.get_attribute("id")

            if not thread_id:
                continue

            thread_id = thread_id.replace("thread-", "")

            # Find preview text
            preview = await card.query_selector(
                "p.text-secondary"
            )

            if not preview:
                continue
            previews_found += 1

            preview_text = (
                await preview.inner_text()
            ).strip()

            print(
                f"Thread {thread_id} "
                f"preview: {preview_text}"
            )

            # Skip our own messages
            if preview_text.lower().startswith("you:"):
                continue

            results.append({
                "thread_id": thread_id,
                "preview": preview_text
            })

        except Exception as e:

            print("Failed parsing thread:", e)

    if record_health:
        # Every account has threads, so an empty or unreadable first inbox
        # page means the list markup changed (or we are not really logged in).
        if not cards:
            page_health.record_step(page_health.INBOX, False, "no thread cards on inbox page")
        elif not previews_found:
            page_health.record_step(
                page_health.INBOX, False, f"{len(cards)} thread cards but no preview text"
            )
        else:
            page_health.record_step(page_health.INBOX, True)

    return results


async def get_all_reply_threads(page):

    all_threads = []

    processed = set()

    # Open first page
    await open_inbox_page(page, start=0)

    total_pages = await get_total_pages(page)

    print(f"\nTotal inbox pages: {total_pages}\n")

    threads = await extract_reply_threads(page, record_health=True)

    for thread in threads:

        thread_id = thread["thread_id"]

        if thread_id in processed:
            continue

        processed.add(thread_id)

        all_threads.append(thread)

    await random_sleep(2, 5)

    for page_num in range(1, total_pages):

        start = page_num * 10

        await open_inbox_page(page, start=start)

        threads = await extract_reply_threads(page)

        for thread in threads:

            thread_id = thread["thread_id"]

            if thread_id in processed:
                continue

            processed.add(thread_id)

            all_threads.append(thread)
        await random_sleep(2, 5)

    return all_threads

async def open_thread(page, thread_id):

    url = (
        f"https://www.openrent.co.uk/messages/"
        f"{thread_id}"
    )

    print(f"\nOpening thread: {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_load_state("load")
    logger.info("THREAD PAGE LOAD COMPLETE")
    print("THREAD PAGE LOAD COMPLETE")
    await close_verified_tenant_popup(page)
    try:
        await page.wait_for_selector(".message-content", timeout=15_000)
    except PlaywrightTimeoutError:
        page_health.record_step(
            page_health.THREAD_READ, False, f"no .message-content on thread {thread_id}"
        )
        raise
    logger.info("THREAD ELEMENT DETECTED")
    print("THREAD ELEMENT DETECTED")
    await close_verified_tenant_popup(page)

async def extract_conversation(page):
    """Messages on the open thread, oldest first, as {sender, message,
    timestamp} with sender "us" or "landlord".

    Raises SenderDetectionError when the page marks none of the messages as
    ours (see OWN_MESSAGE_CLASS). Messages the page fails to mark but whose
    text matches one we stored as sent are corrected to "us"."""

    await close_verified_tenant_popup(page)

    messages = await page.query_selector_all(
        ".message-content"
    )

    results = []
    marked_ours = 0

    for msg in messages:

        try:

            text = await msg.inner_text()

            text = text.strip()

            if not text:
                continue

            # Skip OpenRent auto messages
            classes = await msg.get_attribute("class")

            if not classes:
                classes = ""

            # Detect sender
            sender = "landlord"

            if OWN_MESSAGE_CLASS in classes:
                sender = "us"
                marked_ours += 1

            # Skip autogenerated OpenRent messages
            if "autogenerated-message" in classes:
                continue

            timestamp = await msg.get_attribute(
                "data-message-time"
            )

            results.append({
                "sender": sender,
                "message": text,
                "timestamp": timestamp
            })

        except Exception as e:

            print("Failed parsing message:", e)

    thread_id = _thread_id_from_url(page.url)

    if results and not marked_ours:
        page_health.record_step(
            page_health.THREAD_READ,
            False,
            f"no '{OWN_MESSAGE_CLASS}' message on thread {thread_id} ({len(results)} messages)",
        )
        raise SenderDetectionError(
            f"thread {thread_id}: none of {len(results)} messages marked "
            f"'{OWN_MESSAGE_CLASS}' — own-message selector likely changed"
        )

    stored_keys = _stored_outbound_keys(thread_id)
    if stored_keys:
        for item in results:
            if item["sender"] == "landlord" and is_our_stored_message(item["message"], stored_keys):
                item["sender"] = "us"
                logger.warning(
                    f"SENDER_RECLASSIFIED thread_id={thread_id} "
                    f"message={item['message'][:60]!r} — unmarked but matches a message we sent"
                )

    if results:
        page_health.record_step(page_health.THREAD_READ, True)

    return results

def should_ai_reply(messages):

    if not messages:
        return False

    latest = messages[-1]

    # Only reply if landlord spoke last
    return latest["sender"] == "landlord"

def get_landlord_messages(messages):

    landlord_messages = []

    for msg in messages:

        if msg["sender"] != "landlord":
            continue

        landlord_messages.append(
            msg["message"]
        )

    return landlord_messages

async def send_reply(
    page,
    reply_text
):

    # Scrub AI-tell dashes (em/en) so no outbound reply carries bot-polished
    # punctuation, whatever produced it (LLM, give-out template, cancel...).
    reply_text = strip_ai_dashes(reply_text)

    # Fleet-wide pause: replies have been failing to land on several accounts
    # (OpenRent changed the thread page). Callers treat False as "not sent",
    # so the thread is simply retried once the pause lifts.
    if page_health.is_paused(page_health.REPLIES):
        logger.warning(
            f"REPLY_PAUSED_BREAKER thread_id={_thread_id_from_url(page.url)} — not sending"
        )
        return False

    await close_verified_tenant_popup(page)

    textarea = page.locator(
        "#message-compose-textarea"
    )

    try:
        await textarea.wait_for(timeout=15_000)
    except PlaywrightTimeoutError:
        logger.warning("send_reply: reply textarea not found (session expired or page failed to load)")
        return False

    # Check disabled state
    disabled = await textarea.get_attribute(
        "disabled"
    )

    if disabled is not None:

        print(
            "\nReply box disabled. "
            "Skipping thread."
        )

        return False

    # Click textarea
    await close_verified_tenant_popup(page)
    await textarea.click()

    # Type naturally
    await textarea.type(
        reply_text,
        delay=30
    )

    print("\nAI reply inserted")

    await page.wait_for_timeout(1500)

    submit_button = page.locator(
        "#send-message-button"
    )

    # Verify button enabled
    button_disabled = await submit_button.get_attribute(
        "disabled"
    )

    if button_disabled is not None:

        print(
            "Send button disabled. "
            "Skipping send."
        )

        return False

    await close_verified_tenant_popup(page)
    ours_before = await _count_own_messages(page)
    await submit_button.click()

    confirmed, still_in_box = await _confirm_reply_sent(page, textarea, reply_text, ours_before)
    thread_id = _thread_id_from_url(page.url)
    if confirmed:
        page_health.record_step(page_health.REPLY_SEND, True)
        page_health.record_step(page_health.REPLY_SEEN, True)
        print("AI reply sent")
        return True

    if still_in_box:
        # Our text is still sitting in the box and no new message of ours
        # appeared: the click did not send (a new modal, a moved button).
        # Report not-sent so the thread is retried next run.
        logger.error(f"REPLY_NOT_SENT thread_id={thread_id} — text still in compose box after click")
        page_health.record_step(page_health.REPLY_SEND, False, "text still in compose box after click")
        await _save_send_debug(page, thread_id)
        return False

    # The box emptied but our message was not seen: probably sent, but the page
    # no longer shows it the way we read it. Count it as sent (a retry could
    # double-send) and let the health check flag the drift.
    logger.warning(f"REPLY_SEND_UNCONFIRMED thread_id={thread_id} — box cleared, message not seen")
    page_health.record_step(page_health.REPLY_SEND, True)
    page_health.record_step(page_health.REPLY_SEEN, False, "box cleared but sent message not seen")
    await _save_send_debug(page, thread_id)
    return True


async def _count_own_messages(page):
    try:
        return await page.locator(f".message-content.{OWN_MESSAGE_CLASS}").count()
    except Exception:
        return None


async def _confirm_reply_sent(page, textarea, reply_text, ours_before, timeout_ms=15_000):
    """After clicking send, wait for proof the reply landed: one more message of
    ours on the thread, or our text visible in the thread. Returns
    (confirmed, text_still_in_box)."""
    probe = _match_key(reply_text)[:40]
    still_in_box = False
    waited = 0
    while waited <= timeout_ms:
        await page.wait_for_timeout(1000)
        waited += 1000
        try:
            ours_now = await _count_own_messages(page)
            if ours_before is not None and ours_now is not None and ours_now > ours_before:
                return True, False
            if probe:
                own = page.locator(f".message-content.{OWN_MESSAGE_CLASS}")
                count = await own.count()
                if count and _match_key(await own.nth(count - 1).inner_text()).startswith(probe):
                    return True, False
        except Exception:
            pass  # page mid-navigation after the submit; poll again
        try:
            box = (await textarea.input_value(timeout=2000)) or ""
            still_in_box = bool(probe) and _match_key(box).startswith(probe)
        except Exception:
            still_in_box = False
    return False, still_in_box


async def _save_send_debug(page, thread_id):
    try:
        import os
        from datetime import datetime

        os.makedirs("debug", exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        await page.screenshot(path=f"debug/reply_send_{thread_id}_{stamp}.png", full_page=True)
        with open(f"debug/reply_send_{thread_id}_{stamp}.html", "w", encoding="utf-8") as f:
            f.write(await page.content())
    except Exception as exc:
        logger.warning(f"REPLY_SEND_DEBUG_FAILED thread_id={thread_id} error={exc}")

async def can_reply(page):

    await close_verified_tenant_popup(page)

    textarea = page.locator(
        "#message-compose-textarea"
    )

    try:
        await textarea.wait_for(timeout=15_000)
    except PlaywrightTimeoutError:
        logger.warning("can_reply: reply textarea not found (session expired or page failed to load)")
        return False

    disabled = await textarea.get_attribute(
        "disabled"
    )

    return disabled is None

def get_latest_landlord_message(
    messages
):

    landlord_messages = [

        msg["message"]

        for msg in messages

        if msg["sender"] == "landlord"
    ]

    if not landlord_messages:
        return None

    return landlord_messages[-1]

async def reveal_hidden_phone_number(page):
    try:

        await close_verified_tenant_popup(page)

        # Find reveal link inside message thread
        reveal_link = page.locator(
            "a:has-text('Click here to reveal the contact information now')"
        )

        if await reveal_link.count() == 0:
            return False

        print("\nHidden contact link found")
        
        await reveal_link.first.click()

        # Wait for popup/modal
        modal_button = page.locator(
            "button:has-text('Proceed: I understand the risks')"
        )

        await modal_button.wait_for(timeout=5000)

        print("Risk popup detected")

        await modal_button.click()

        # Wait for number/message to refresh
        await page.wait_for_timeout(3000)

        print("Contact information revealed")

        return True

    except PlaywrightTimeoutError:
        print("Reveal popup timeout")
        return False

    except Exception as e:
        print(f"Failed revealing contact info: {e}")
        return False
