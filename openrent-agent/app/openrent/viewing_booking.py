"""Withdraw a booked viewing through OpenRent's own Cancel Viewing form.

A chat "something came up" message leaves the booking live on OpenRent. Once
the time passes the thread shows "Viewing Conducted" and the landlord can
decline us with "You didn't show up to the viewing", which OpenRent records
(334 such flags since June; 161 on viewings we had already cancelled in chat).

The tenant side of a booked viewing has a "Cancel / Rearrange Viewing" link to
/enquiries/cancelviewing: a reason box (RejectionReason) and two submit buttons,
cancellationType=rearrange ("Request New Viewing Appointment") and
cancellationType=cancel ("Cancel Viewing and Withdraw Enquiry"). We use cancel,
which removes the booking and tells the landlord the application was withdrawn.
Viewings agreed only in chat have no booking and no link ("no_booking").
"""
import os
import zlib

from app.db.repository import (
    claim_conversation,
    get_booking_withdrawal_candidates,
    record_booking_cancel_result,
    release_conversation_claim,
)
from app.openrent.inbox import open_thread
from app.openrent.popups import close_verified_tenant_popup
from app.services import page_health
from app.utils.human import random_sleep
from app.utils.logger import logger

CANCEL_LINK = "a[href*='/enquiries/cancelviewing']"
REASON_BOX = "textarea#RejectionReason"
CANCEL_BUTTON = "button[name='cancellationType'][value='cancel']"

# What the landlord sees as the cancellation reason. The chat message already
# explained, so keep it short and plain.
_REASONS = (
    "Sorry, something has come up and I can't make the viewing.",
    "Really sorry, I can't make it to the viewing anymore.",
    "Sorry, my plans have changed and I won't be able to make the viewing.",
)


def booking_cancel_enabled() -> bool:
    return os.getenv("OPENRENT_BOOKING_CANCEL", "1") != "0"


def cancellation_reason(thread_id) -> str:
    return _REASONS[zlib.crc32(str(thread_id).encode()) % len(_REASONS)]


async def cancel_openrent_booking(page, thread_id) -> str:
    """Withdraw the thread's OpenRent booking. The page must be on the thread.

    Returns "cancelled", "no_booking", "disabled" or "failed:<why>", records the
    outcome, and never raises: a failure here must not undo the chat cancel.
    Leaves the page on the thread.
    """
    if not booking_cancel_enabled():
        return "disabled"
    try:
        result = await _submit_cancel_form(page, thread_id)
    except Exception as exc:
        result = f"failed:{type(exc).__name__}"
        logger.warning(f"OPENRENT_BOOKING_CANCEL_ERROR thread_id={thread_id} error={exc}")
    if result == "cancelled":
        page_health.record_step(page_health.BOOKING_CANCEL, True)
    elif result.startswith("failed:"):
        page_health.record_step(page_health.BOOKING_CANCEL, False, f"thread {thread_id}: {result}")
    try:
        record_booking_cancel_result(thread_id, result)
    except Exception as exc:
        logger.warning(f"OPENRENT_BOOKING_CANCEL_RECORD_FAILED thread_id={thread_id} error={exc}")
    logger.info(f"OPENRENT_BOOKING_CANCEL thread_id={thread_id} result={result}")
    return result


async def _submit_cancel_form(page, thread_id) -> str:
    link = page.locator(CANCEL_LINK).first
    if await link.count() == 0:
        return "no_booking"
    href = await link.get_attribute("href")
    url = href if href.startswith("http") else f"https://www.openrent.co.uk{href}"

    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await close_verified_tenant_popup(page)
    reason_box = page.locator(REASON_BOX)
    cancel_button = page.locator(CANCEL_BUTTON)
    if await reason_box.count() == 0 or await cancel_button.count() == 0:
        await open_thread(page, thread_id)
        return "failed:no_form"

    await reason_box.fill(cancellation_reason(thread_id))
    await random_sleep(1, 3)
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
        await cancel_button.first.click()
    logger.info(f"OPENRENT_BOOKING_CANCEL_SUBMITTED thread_id={thread_id} landed={page.url}")

    # Verify on the thread itself: a withdrawn booking has no cancel link.
    await open_thread(page, thread_id)
    if await page.locator(CANCEL_LINK).count():
        return "failed:still_booked"
    return "cancelled"


async def withdraw_leftover_bookings(account, page, owner):
    """Withdraw bookings for viewings we cancelled without the form: WhatsApp
    cancels, in-reply withdrawals, and chat cancels sent before this existed."""
    if not booking_cancel_enabled():
        return
    thread_ids = get_booking_withdrawal_candidates(account.id)
    if not thread_ids:
        return
    logger.info(
        f"OPENRENT_BOOKING_LEFTOVERS account_id={account.id} count={len(thread_ids)}"
    )
    for thread_id in thread_ids:
        if not claim_conversation(thread_id, owner):
            continue
        try:
            await open_thread(page, thread_id)
            await cancel_openrent_booking(page, thread_id)
        except Exception as exc:
            logger.warning(
                f"OPENRENT_BOOKING_LEFTOVER_FAILED thread_id={thread_id} error={exc}"
            )
            record_booking_cancel_result(thread_id, f"failed:{type(exc).__name__}")
        finally:
            release_conversation_claim(thread_id, owner)
        await random_sleep(2, 5)
