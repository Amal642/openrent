from app.db.repository import (
    account_stop_requested,
    claim_conversation,
    ensure_account_persona,
    release_conversation_claim,
    save_ai_reply,
    save_inbound_messages,
    save_message,
    save_phone_number,
    update_conversation_stage,
    update_conversation_status,
    get_conversation_by_thread_id,
    get_automatic_cancellation_block_reason,
    viewing_cancellation_due,
    update_last_processed_message,
    phone_exists,
    mark_handoff_complete,
    mark_phone_requested,
    mark_phone_number_shared,
    mark_landlord_asked_phone,
    mark_our_number_shared,
    update_conversation_memory,
    save_viewing_datetime,
    save_banner_state,
    count_phones_today,
    get_thread_property_location,
    get_travel_city,
    save_travel_city,
    get_playbook_ab_enrollment_state,
    increment_follow_up_count,
    reset_follow_up_count,
    mark_conversation_inactive,
)


from app.openrent.inbox import (
    get_all_reply_threads,
    get_landlord_messages,
    open_thread,
    extract_conversation,
    should_ai_reply,
    can_reply,
    get_latest_landlord_message,
    send_reply,
    reveal_hidden_phone_number
)
from app.openrent.banner_parser import extract_thread_banners
from app.openrent.popups import close_verified_tenant_popup

from app.ai.stages import (
    detect_stage,
    extract_viewing_datetime,
    resolve_viewing_datetime,
)

from app.ai.extractors import (
    ai_extract_phone,
    regex_extract_phone
)

from app.ai.replies import (
    ai_detect_viewing_arranged,
    generate_handoff_message,
    generate_reply,
    generate_distant_location,
    generate_follow_up_message,
    detect_short_term_tenancy,
    generate_short_term_close_message,
    count_number_asks,
)

import os  # OPEN-21D playbook A/B
from app.experiments import playbook_ab  # OPEN-21D playbook A/B

from app.ai.validators import (
    remove_unapproved_phone_numbers
)
from app.ai.personas import tenant_shared_phone
from app.ai.reply_gate import post_capture_decision, landlord_wants_video_call

# Viewing-withdrawal lifecycle helpers (cancel / pre-cancel number-ask / give-out
# salvage) live in one shared module so the DB-driven cancellation sweep can reuse
# the exact same behaviour. Re-imported here so every existing call site is
# unchanged (the video-call gate below still calls _try_giveout_salvage). NOTE:
# these resolve their deps in viewing_lifecycle's namespace, so tests must
# monkeypatch app.openrent.viewing_lifecycle.<name>.
from app.openrent.viewing_lifecycle import (
    _cancel_viewing_and_handoff,
    _send_pre_cancel_number_ask,
    _try_giveout_salvage,
)

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    detect_screening_questions,
    latest_landlord_asked_for_phone,
    latest_landlord_hesitant_about_phone,
)

from app.utils.phone import (
    normalize_uk_phone
)
from app.utils.logger import logger
from app.alerts.events import report_error

from app.db.status import (
    SKIPPED,
    PHONE_ACQUIRED,
    DUPLICATE_LEAD,
    REPLY_DISABLED,
    AI_FAILED,
    AI_REPLIED,
    HANDOFF_COMPLETE,
    VIEWING_BOOKED,
    VIEWING_PENDING,
    VIEWING_CANCELLED,
    INACTIVE_NO_REPLY,
    SHORT_TERM_PROPERTY,
)

from datetime import datetime, timezone, timedelta
import random
import re
from pathlib import Path


async def _screenshot_thread(page, thread_id: str, label: str | None = None) -> None:
    """Save a full-page screenshot as screenshots/threads/<thread_id>/<n>.png.
    Each call increments the counter so the full history is preserved."""
    try:
        folder = Path("screenshots") / "threads" / str(thread_id)
        folder.mkdir(parents=True, exist_ok=True)
        existing = [f for f in folder.iterdir() if f.suffix == ".png" and f.stem.isdigit()]
        next_n = len(existing) + 1
        filename = f"{next_n}.png"
        path = str(folder / filename)
        await page.screenshot(path=path, full_page=True)
        tag = f" label={label}" if label else ""
        logger.info(f"THREAD_SCREENSHOT_SAVED thread_id={thread_id} path={path}{tag}")
    except Exception as exc:
        logger.warning(f"THREAD_SCREENSHOT_FAILED thread_id={thread_id} error={exc}")


def _parse_message_timestamp(value):
    if not value:
        return None

    value = str(value).strip()
    if not value:
        return None

    try:
        if value.isdigit():
            numeric = int(value)
            if numeric > 10_000_000_000:
                numeric = numeric / 1000
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass

    for candidate in (
        value,
        value.replace("Z", "+00:00"),
    ):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            pass

    return None


def _latest_message_by_sender(messages, senders):
    latest = None
    latest_ts = None

    for message in messages or []:
        if message.get("sender") not in senders:
            continue

        timestamp = _parse_message_timestamp(message.get("timestamp"))

        if latest is None:
            latest = message
            latest_ts = timestamp
            continue

        if timestamp and latest_ts:
            if timestamp >= latest_ts:
                latest = message
                latest_ts = timestamp
        else:
            latest = message
            latest_ts = timestamp

    return latest, latest_ts


def _thread_has_unanswered_landlord_message(messages, conversation):
    latest_landlord, latest_landlord_ts = _latest_message_by_sender(
        messages,
        {"landlord"},
    )
    latest_reply, latest_reply_ts = _latest_message_by_sender(
        messages,
        {"us", "ai", "user"},
    )

    if not latest_landlord:
        return False, latest_landlord, latest_reply, latest_reply_ts

    if not latest_reply:
        return True, latest_landlord, latest_reply, latest_reply_ts

    if latest_landlord_ts and latest_reply_ts:
        return (
            latest_landlord_ts > latest_reply_ts,
            latest_landlord,
            latest_reply,
            latest_reply_ts,
        )

    processed = conversation.last_processed_message if conversation else None
    return (
        processed != latest_landlord.get("message"),
        latest_landlord,
        latest_reply,
        latest_reply_ts,
    )


def _is_name_question(message):
    text = (message or "").lower()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    patterns = [
        r"\bwhat is your name\b",
        r"\bwhat's your name\b",
        r"\bcould i take your name\b",
        r"\bcan i take your name\b",
        r"\bmay i take your name\b",
        r"\bwhat should i call you\b",
        r"\bwho should i ask for\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)


def _build_name_reply(persona):
    name = (persona or {}).get("persona_name") or (persona or {}).get("name")
    if not name:
        return None
    return (
        f"Of course, my name is {name}. "
        "Looking forward to meeting you."
    )


# Graceful sign-offs sent once when a thread is FIRST found to be a duplicate
# (its number is one we already captured on another thread), so an engaged
# landlord is not simply ghosted. Deterministic + rotated by thread id for
# variety; plain tenant "found somewhere else" wording, no dashes, no tells.
_DUPLICATE_CLOSE_MSGS = [
    "Thanks so much for your help with this. We've actually just found a place that suits us, so we won't need the viewing after all. Really appreciate your time and all the best with the let.",
    "Thank you for getting back to me. Our plans have shifted and we've ended up going with somewhere else, so I'll leave it here. Wishing you all the best.",
    "Really appreciate you sorting this out. Something else came through for us in the end, so we won't be going ahead, but thanks a lot for your time.",
    "Thanks for the details. We've had a change of plan and won't need to view after all, sorry for any hassle. All the best!",
]


def _has_active_viewing(conversation) -> bool:
    """True when a viewing has been booked, confirmed, or a datetime recorded."""
    return bool(
        getattr(conversation, "viewing_confirmed", False)
        or getattr(conversation, "viewing_requested", False)
        or getattr(conversation, "viewing_datetime", None) is not None
    )


# Cold-lead follow-up cadence: day1 initial, day2 follow-up1, day3 follow-up2,
# day4 still silent -> mark inactive. Only applies to threads where the
# landlord has never sent a single message.
FOLLOW_UP_MAX = 2
FOLLOW_UP_INTERVAL_DAYS = 1.0

# Warm-lead nudge: the landlord replied and engaged (e.g. we asked for their
# number) but then went silent. Unlike cold leads, these threads are still open
# and recoverable, so send a gentle follow-up on a slower cadence rather than
# letting the lead decay. WARM_FOLLOW_UP_STALE_DAYS caps the first nudge so
# long-dormant threads (existing backlog) are left untouched — the cadence only
# picks up leads that go quiet going forward.
WARM_FOLLOW_UP_MAX = 2
WARM_FOLLOW_UP_INTERVAL_DAYS = 2.0
WARM_FOLLOW_UP_STALE_DAYS = 5.0


def _cancel_window_passed(viewing_dt) -> bool:
    """True if the viewing is within the 3–5h cancel window.
    Returns False when viewing_dt is unknown — we never cancel blind."""
    if viewing_dt is None:
        return False
    hours_until = (viewing_dt - datetime.utcnow()).total_seconds() / 3600
    cancel_threshold = random.uniform(3.0, 5.0)
    return hours_until <= cancel_threshold


def _parse_ai_viewing_datetime(dt_str):
    """Convert 'YYYY-MM-DD HH:MM' string from AI detection to a datetime object."""
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(dt_str).strip(), fmt)
        except ValueError:
            continue
    return None


def _should_run_viewing_detection(banners) -> bool:
    """Run AI viewing-detection whenever the viewing is not already confirmed.

    This deliberately runs even when a "Request Viewing" banner is present.
    Landlords usually confirm a viewing in free-text chat, not via OpenRent's
    button, so gating on the request banner left those bookings undetected
    (viewing_confirmed stayed False -> the 3-5h cancellation strategy never
    fired -> no-shows). The detector requires MUTUAL agreement AND a specific
    datetime before promoting, so a one-sided tenant request cannot
    false-positive.
    """
    return not banners["viewing_confirmed"]


def _assign_playbook_ab_if_enabled(thread_id, persona):
    """Assign only a fresh thread, immediately before its first controlled reply."""
    if os.getenv("PLAYBOOK_AB_ENABLED") != "1":
        return None

    assignment_log = os.getenv(
        "PLAYBOOK_AB_LOG",
        "logs/playbook_ab_assignments.jsonl",
    )
    existing = playbook_ab.get_assignment(thread_id, assignment_log)
    if existing:
        return existing

    eligibility = playbook_ab.enrollment_eligibility(
        get_playbook_ab_enrollment_state(thread_id)
    )
    if not eligibility["eligible"]:
        exclusion_log = os.getenv(
            "PLAYBOOK_AB_EXCLUSION_LOG",
            "logs/playbook_ab_exclusions.jsonl",
        )
        playbook_ab.log_exclusion(thread_id, exclusion_log, eligibility)
        logger.info(
            f"PLAYBOOK_AB_EXCLUDED thread_id={thread_id} "
            f"reasons={eligibility['reasons']}"
        )
        return None

    assignment = playbook_ab.assign(
        thread_id,
        persona,
        assignment_log,
        eligibility=eligibility,
    )
    logger.info(
        f"PLAYBOOK_AB thread_id={thread_id} arm={assignment['assigned_arm']} "
        f"design={assignment['assigned_design_id']} expose_mobile={assignment['expose_mobile']}"
    )
    return assignment


def _log_playbook_ab_phone_capture(thread_id):
    """Record a capture immediately after the authoritative database write."""
    if os.getenv("PLAYBOOK_AB_ENABLED") != "1":
        return

    assignment = playbook_ab.get_assignment(
        thread_id,
        os.getenv("PLAYBOOK_AB_LOG", "logs/playbook_ab_assignments.jsonl"),
    )
    if not assignment:
        return

    try:
        playbook_ab.log_outcome(
            thread_id,
            os.getenv(
                "PLAYBOOK_AB_OUTCOME_LOG",
                "logs/playbook_ab_outcomes.jsonl",
            ),
            event="phone_capture",
            landlord_phone_captured=True,
            source_of_truth="database.conversations.phone_found_at",
        )
    except Exception as exc:
        logger.warning(
            f"PLAYBOOK_AB capture log failed thread_id={thread_id}: {exc}"
        )


async def _send_duplicate_close(thread_id, conversation, messages, page, was_duplicate):
    """Send one graceful sign-off the FIRST time a thread is found to be a
    duplicate, so an engaged landlord is not left hanging.

    Only for NEW duplicates: ``was_duplicate`` (the thread's status captured at
    the start of this run) is True for the existing backlog, which we leave
    untouched. ``conversation._dup_close_done`` guards against a second send in
    the same run, since the early-dup path and the phone-detect path can both
    fire. No-op on cold threads the landlord never replied to.
    """
    if conversation is None or was_duplicate:
        return
    if getattr(conversation, "_dup_close_done", False):
        return
    if not get_landlord_messages(messages):
        return
    conversation._dup_close_done = True  # set before send so it can't double-fire
    try:
        idx = int(str(thread_id)) % len(_DUPLICATE_CLOSE_MSGS)
    except (TypeError, ValueError):
        idx = 0
    msg = _DUPLICATE_CLOSE_MSGS[idx]
    sent = await send_reply(page, msg)
    if sent:
        save_message(thread_id, "outbound", msg)
        logger.info(f"DUPLICATE_LEAD_CLOSE_SENT thread_id={thread_id}")
    else:
        logger.warning(f"DUPLICATE_LEAD_CLOSE_SEND_FAILED thread_id={thread_id}")


async def _try_save_viewing_datetime(thread_id, messages) -> bool:
    """
    Extract a viewing datetime from messages and save it to DB.
    Returns True if a datetime was found and saved, False otherwise.
    Cancellation timing is handled separately via _cancel_window_passed.
    """
    viewing_datetime = resolve_viewing_datetime(messages)
    if not viewing_datetime:
        return False

    save_viewing_datetime(thread_id, viewing_datetime)
    logger.info(
        f"VIEWING_DATETIME_LATE_EXTRACTED thread_id={thread_id} "
        f"viewing_datetime={viewing_datetime}"
    )
    return True


async def _send_handoff_message(
    thread_id, messages, latest_landlord_message, page, message=None, persona=None
):
    logger.info("PHONE NUMBER EXTRACTED")

    if message:
        handoff_message = message
        handoff_error = None
    else:
        handoff_message, handoff_error = generate_handoff_message(messages)

    if not handoff_message or handoff_error:
        logger.error(
            f"Handoff message generation failed for thread {thread_id}: "
            f"{handoff_error or 'empty_handoff_message'}"
        )
        return False

    logger.info("HANDOFF MESSAGE GENERATED")

    sent = await send_reply(page, handoff_message)
    if not sent:
        still_open = await can_reply(page)
        if not still_open:
            logger.warning(
                f"HANDOFF_REPLY_DISABLED thread_id={thread_id} "
                "textarea disabled — marking reply_disabled"
            )
            update_conversation_status(thread_id, REPLY_DISABLED)
        else:
            logger.warning(f"Handoff message send failed for thread {thread_id}")
        return False

    logger.info("HANDOFF MESSAGE SENT")
    save_message(thread_id, "outbound", handoff_message)
    update_last_processed_message(thread_id, latest_landlord_message)
    mark_handoff_complete(thread_id)
    update_conversation_status(thread_id, HANDOFF_COMPLETE)
    logger.info(f"HANDOFF_COMPLETE thread_id={thread_id}")
    logger.info("CONVERSATION HANDOFF COMPLETE")
    return True

async def process_account_replies(
    account,
    page,
    worker_id=None
):



    threads = await get_all_reply_threads(page)

    logger.info(f"REPLIES_STARTED account_id={account.id} threads={len(threads)}")

    for thread in threads:
        thread_id = None

        try:
            if account_stop_requested(account.id):
                logger.info(
                    f"Reply processing stopped for account {account.id}"
                )
                break

            thread_id = thread["thread_id"]
            owner = worker_id or f"account-{account.id}"

            if not claim_conversation(thread_id, owner):
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    "reason=already_claimed"
                )
                logger.info(f"Thread {thread_id} already claimed. Skipping.")
                continue

            await open_thread(page, thread_id)

            messages = await extract_conversation(page)

            # Banner detection — primary source of truth for viewing state.
            # Run before saving messages so the conversation fetch below
            # already reflects the banner-derived state.
            banners = await extract_thread_banners(page)
            if banners["viewing_confirmed"]:
                save_banner_state(
                    thread_id,
                    viewing_requested=banners["viewing_requested"],
                    viewing_confirmed=True,
                    viewing_datetime=banners["viewing_datetime"],
                )
            elif banners["viewing_requested"]:
                save_banner_state(thread_id, viewing_requested=True)

            # AI viewing detection — determines if a viewing is genuinely arranged
            # from the chat. Result is merged into `banners` so the cancel block and
            # all downstream logic use one consistent dict.
            #
            # Runs whenever the viewing is not already confirmed — INCLUDING when a
            # "Request Viewing" banner is present. Landlords usually confirm in
            # free-text chat, not via OpenRent's button, so gating on the request
            # banner left those bookings undetected (viewing_confirmed stayed False
            # -> the cancellation strategy never fired -> no-shows). The detector
            # requires MUTUAL agreement AND a specific datetime before promoting
            # (see _should_run_viewing_detection), so a one-sided tenant request
            # cannot false-positive.
            if _should_run_viewing_detection(banners):
                ai_viewing = ai_detect_viewing_arranged(messages)
                if ai_viewing.get("viewing_arranged"):
                    # The LLM only DECIDES a viewing is agreed; the datetime is
                    # resolved deterministically (message-anchored), with the
                    # LLM's own date used only as a gap-filler. Keeps the LLM
                    # out of date arithmetic (the off-by-one-day no-show,
                    # thread 45969788).
                    ai_dt = resolve_viewing_datetime(messages, llm_detection=ai_viewing)
                    # Only promote to confirmed when the AI also identified a
                    # specific datetime. A viewing with no agreed time is not
                    # truly "booked" and must not enter the cancel flow.
                    if ai_dt:
                        banners["viewing_confirmed"] = True
                        banners["viewing_datetime"] = ai_dt
                        save_banner_state(
                            thread_id,
                            viewing_confirmed=True,
                            viewing_datetime=ai_dt,
                            confirmation_source="ai",
                        )
                        logger.info(
                            f"AI_VIEWING_DETECTED thread_id={thread_id} "
                            f"datetime={ai_dt} reason={ai_viewing.get('reason')!r}"
                        )
                    else:
                        logger.info(
                            f"AI_VIEWING_DETECTED_NO_DATETIME thread_id={thread_id} "
                            f"reason={ai_viewing.get('reason')!r} "
                            "— not promoting to confirmed (no specific time agreed)"
                        )
                else:
                    logger.info(
                        f"AI_VIEWING_NOT_DETECTED thread_id={thread_id} "
                        f"reason={ai_viewing.get('reason')!r}"
                    )

            save_inbound_messages(thread_id, messages)

            conversation = (
                get_conversation_by_thread_id(
                    thread_id
                )
            )

            # Was this thread ALREADY a duplicate before this run? Used to send a
            # one-time graceful close on NEW duplicates only, leaving the backlog
            # of previously-deduped threads untouched.
            _was_duplicate = bool(
                conversation and conversation.status == DUPLICATE_LEAD
            )

            # DUPLICATE_LEAD is terminal: the number is already captured on the
            # sibling thread. Stop reprocessing the backlog every run (it looped
            # via the early-phone regex + re-mark). New duplicates are still
            # detected below on their first run (status not yet DUPLICATE_LEAD).
            if _was_duplicate:
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} reason=duplicate_lead"
                )
                continue

            # Dead stale viewing: a confirmed viewing well in the past, no phone
            # captured, and no activity for a day, is a no-show we can no longer
            # act on. Skip it SILENTLY (no message, no LLM, no status change) so it
            # stops churning through the early-phone / cancel / salvage / send-fail
            # machinery every run. Deliberately does NOT reply: the only pending
            # messages on these are stale "you didn't show up" / rejections, and a
            # late generic reply would read as a bot. If the landlord ever messages
            # again, last_message_at becomes recent and this stops matching, so the
            # thread reactivates on its own.
            _now_sv = datetime.utcnow()
            if (
                conversation
                and conversation.viewing_datetime
                and conversation.viewing_datetime < _now_sv - timedelta(hours=48)
                and not conversation.extracted_phone
                and not getattr(conversation, "viewing_cancelled", False)
                and conversation.last_message_at
                and conversation.last_message_at < _now_sv - timedelta(hours=24)
                and conversation.conversation_stage not in (
                    HANDOFF_COMPLETE, VIEWING_CANCELLED, SHORT_TERM_PROPERTY
                )
            ):
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    f"reason=stale_viewing viewing_dt={conversation.viewing_datetime}"
                )
                continue

            # CAPTURE-FIRST (root-cause fix): a landlord's number can arrive at
            # any stage, but phone extraction used to run only in the reply path
            # far below, which the viewing-cancel / follow-up / skip gates skip.
            # 16/17 recent number-losses were confirmed viewings whose number was
            # saved here but never extracted before the cancel gate fired. Extract
            # up front (regex + split-message stitching) so the number is secured
            # before any gate; the fuller reveal + AI extraction still runs later
            # in the reply path as a backstop for hidden/masked numbers.
            if conversation and not conversation.extracted_phone:
                _early_phone = regex_extract_phone(get_landlord_messages(messages))
                if _early_phone:
                    _early_phone = normalize_uk_phone(_early_phone)
                if _early_phone:
                    if phone_exists(_early_phone):
                        logger.info(
                            f"PHONE_CAPTURED_EARLY_DUPLICATE thread_id={thread_id} phone={_early_phone}"
                        )
                        await _send_duplicate_close(
                            thread_id, conversation, messages, page, _was_duplicate
                        )
                        update_conversation_status(thread_id, DUPLICATE_LEAD)
                        continue
                    else:
                        save_phone_number(thread_id, _early_phone)
                        _log_playbook_ab_phone_capture(thread_id)
                        logger.info(
                            f"PHONE_CAPTURED_EARLY thread_id={thread_id} phone={_early_phone}"
                        )
                        # Refresh so the gates below (P1 stop, viewing-cancel) see
                        # the captured number and handle handoff/cancellation.
                        conversation = get_conversation_by_thread_id(thread_id)

            (
                has_unanswered_landlord_message,
                latest_landlord_entry,
                latest_reply_entry,
                latest_reply_timestamp,
            ) = _thread_has_unanswered_landlord_message(
                messages,
                conversation,
            )

            latest_landlord_message = (
                latest_landlord_entry.get("message")
                if latest_landlord_entry
                else get_latest_landlord_message(messages)
            )

            logger.info(
                f"LATEST_LANDLORD_MESSAGE thread_id={thread_id} "
                f"message={latest_landlord_message!r}"
            )
            logger.info(
                f"LATEST_REPLY_TIMESTAMP thread_id={thread_id} "
                f"timestamp={latest_reply_timestamp.isoformat() if latest_reply_timestamp else None}"
            )
            logger.info(
                f"THREAD_HAS_UNANSWERED_LANDLORD_MESSAGE thread_id={thread_id} "
                f"value={has_unanswered_landlord_message}"
            )

            # Reactivate a cold lead the moment the landlord finally replies —
            # a late reply is still a real lead, don't leave it stuck inactive.
            if (
                has_unanswered_landlord_message
                and conversation
                and (
                    conversation.status == INACTIVE_NO_REPLY
                    or (conversation.follow_up_count or 0) > 0
                )
            ):
                logger.info(
                    f"CONVERSATION_REACTIVATED thread_id={thread_id} "
                    f"previous_status={conversation.status} "
                    f"follow_up_count={conversation.follow_up_count}"
                )
                reset_follow_up_count(thread_id)

            if has_unanswered_landlord_message:
                await _screenshot_thread(page, thread_id)

            if conversation and conversation.conversation_stage in (
                HANDOFF_COMPLETE, VIEWING_CANCELLED, SHORT_TERM_PROPERTY
            ):
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    f"reason={conversation.conversation_stage.lower()}"
                )
                # Sync status so a stale AI_FAILED doesn't show on the dashboard
                # for threads that already completed (just the status column lagged).
                if conversation.status == "AI_FAILED":
                    update_conversation_status(thread_id, conversation.conversation_stage)

                # When the viewing was cancelled and the landlord replies back,
                # check for a phone number first. If found, save it. Either way,
                # track whether a number was obtained so we can decide whether
                # to reply or permanently skip this thread.
                _late_phone_found = False
                if (
                    conversation.conversation_stage == VIEWING_CANCELLED
                    and not conversation.extracted_phone
                    and has_unanswered_landlord_message
                    and latest_landlord_entry
                ):
                    _check_texts = get_landlord_messages(messages)
                    _late_phone = regex_extract_phone(_check_texts) or ai_extract_phone(_check_texts)
                    if _late_phone:
                        _late_phone = normalize_uk_phone(_late_phone)
                    if _late_phone and not phone_exists(_late_phone):
                        logger.info(
                            f"PHONE_FOUND_AFTER_CANCEL thread_id={thread_id} "
                            f"phone={_late_phone}"
                        )
                        save_phone_number(thread_id, _late_phone)
                        _log_playbook_ab_phone_capture(thread_id)
                        _late_phone_found = True
                    elif _late_phone:
                        logger.info(
                            f"PHONE_DUPLICATE_AFTER_CANCEL thread_id={thread_id} "
                            f"phone={_late_phone}"
                        )
                        _late_phone_found = True  # treat duplicate as obtained

                # VIEWING_CANCELLED + landlord replied + still no phone →
                # fall through to the normal reply flow so the AI can re-engage
                # and naturally ask for the landlord's WhatsApp/number.
                # All other cases (HANDOFF_COMPLETE, phone already obtained,
                # no new landlord message) are permanently skipped.
                _should_reply_after_cancel = (
                    conversation.conversation_stage == VIEWING_CANCELLED
                    and not conversation.extracted_phone
                    and not _late_phone_found
                    and has_unanswered_landlord_message
                )
                if not _should_reply_after_cancel:
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

                # We cancelled on the landlord — do NOT fall through to the
                # generic reply prompt. It has no idea we withdrew and emits a
                # backwards closer ("if anything changes on your end, keep me in
                # mind") as if THEY lost interest in us. Share our WhatsApp
                # give-out once (a willing-but-redacted landlord can still reach
                # us), then go quiet rather than re-asking for a number they
                # already told us OpenRent blocks.
                await _try_giveout_salvage(
                    thread_id, conversation, account, messages,
                    latest_landlord_message, page, require_landlord_asked=False,
                )
                update_last_processed_message(thread_id, latest_landlord_message)
                logger.info(
                    f"POST_CANCEL_QUIET thread_id={thread_id} "
                    "reason=we_withdrew — no generic re-engage"
                )
                continue

            # Viewing confirmed — 2-step cancel flow:
            #   Step 1: ask for landlord's number (pre-cancel ask)
            #   Step 2: cancel on next run (phone_requested_at will be set)
            #
            # Timing rules:
            #   • No datetime extracted → ask for number now; cancel next run
            #   • Viewing ≤ random(3–5h) away → ask for number; cancel next run
            #   • Viewing > cancel threshold → AI replies normally (asks for number
            #     naturally via VIEWING_BOOKED prompt); reminder handles timed cancel
            #
            # Banner is primary source of truth. Fallback: banner gone but DB has
            # a past uncancelled viewing_datetime → treat as in cancel window.
            _db_viewing_dt = getattr(conversation, "viewing_datetime", None) if conversation else None
            # Fallback only fires when the DB has a confirmed viewing but the
            # banner is gone (landlord cleared it on their side). If the
            # "Viewing Requested" banner is still showing the viewing was never
            # confirmed, so we must not enter the cancel flow.
            _fallback_cancel = (
                not banners["viewing_confirmed"]
                and not banners.get("viewing_requested")
                and conversation
                and getattr(conversation, "viewing_confirmed", False)
                and not getattr(conversation, "viewing_cancelled", False)
                and not conversation.handoff_completed_at
                and _db_viewing_dt is not None
                and _cancel_window_passed(_db_viewing_dt)
            )
            if _fallback_cancel:
                logger.info(
                    f"VIEWING_CANCEL_FALLBACK thread_id={thread_id} reason=past_datetime_no_banner "
                    f"viewing_dt={_db_viewing_dt}"
                )
            if (
                (banners["viewing_confirmed"] or _fallback_cancel)
                and (not conversation or (
                    not getattr(conversation, "viewing_cancelled", False)
                    and not conversation.handoff_completed_at
                ))
            ):
                viewing_dt = getattr(conversation, "viewing_datetime", None)
                phone_already_requested = bool(conversation and conversation.phone_requested_at)

                # Timed withdrawal (give-out salvage / pre-cancel number-ask /
                # cancellation) is owned entirely by the Phase-2 sweep
                # (process_account_viewing_reminders): DB-driven, inbox-independent,
                # and it runs right after this reply pass every cycle. When a viewing
                # with a known time is inside its cancel window, defer to the sweep —
                # so we never emit a normal reply moments before a withdrawal, and so
                # the withdrawal fires even when this thread is filtered out of the
                # reply inbox (the "you:" filter). Same viewing_cancellation_due()
                # predicate the sweep uses, so the two can't disagree. (The sweep does
                # the salvage-before-cancel with require_landlord_asked=False, matching
                # the Sandra/Claire fix that previously lived here.)
                if viewing_cancellation_due(conversation):
                    update_last_processed_message(thread_id, latest_landlord_message)
                    logger.info(
                        f"VIEWING_WITHDRAWAL_DEFERRED_TO_SWEEP thread_id={thread_id} "
                        f"viewing_dt={viewing_dt}"
                    )
                    continue

                # No parsed viewing time: the timed sweep cannot schedule these
                # (there is no datetime to time a cancel against), so keep the one-off
                # number-ask here. Asking captures the lead; nothing to cancel.
                if viewing_dt is None and not phone_already_requested:
                    logger.info(f"VIEWING_NO_DATETIME_NUMBER_ASK thread_id={thread_id}")
                    travel_city_for_ask = get_travel_city(thread_id)
                    await _send_pre_cancel_number_ask(
                        thread_id, messages, latest_landlord_message, page,
                        travel_city=travel_city_for_ask,
                    )
                    continue

                # Outside the cancel window (known future time) or no datetime but
                # already asked: fall through and reply naturally.
                if viewing_dt is not None:
                    hours_until = (viewing_dt - datetime.utcnow()).total_seconds() / 3600
                    logger.info(
                        f"VIEWING_CANCEL_DEFERRED thread_id={thread_id} "
                        f"hours_until={hours_until:.1f} — replying naturally while awaiting cancel window"
                    )

            if (
                conversation
                and
                conversation.last_processed_message
                ==
                latest_landlord_message
                and not has_unanswered_landlord_message
            ):
                # Cold lead: landlord has never sent a single message. Apply the
                # daily follow-up cadence instead of skipping forever.
                if not latest_landlord_message and conversation.status != INACTIVE_NO_REPLY:
                    last_outbound = conversation.last_outbound_at or conversation.created_at
                    days_silent = (
                        (datetime.utcnow() - last_outbound).total_seconds() / 86400
                        if last_outbound else 0
                    )
                    follow_up_count = conversation.follow_up_count or 0

                    if days_silent < FOLLOW_UP_INTERVAL_DAYS:
                        update_conversation_status(thread_id, SKIPPED)
                    elif follow_up_count < FOLLOW_UP_MAX:
                        follow_up_msg, err = generate_follow_up_message(
                            messages, follow_up_number=follow_up_count + 1
                        )
                        if follow_up_msg:
                            sent = await send_reply(page, follow_up_msg)
                            if sent:
                                save_message(thread_id, "outbound", follow_up_msg)
                                new_count = increment_follow_up_count(thread_id)
                                logger.info(
                                    f"FOLLOW_UP_SENT thread_id={thread_id} "
                                    f"number={new_count} days_silent={days_silent:.1f}"
                                )
                            else:
                                still_open = await can_reply(page)
                                if not still_open:
                                    update_conversation_status(thread_id, REPLY_DISABLED)
                                logger.warning(
                                    f"FOLLOW_UP_SEND_FAILED thread_id={thread_id}"
                                )
                        else:
                            logger.warning(
                                f"FOLLOW_UP_GENERATION_FAILED thread_id={thread_id} error={err}"
                            )
                    else:
                        mark_conversation_inactive(thread_id)
                        logger.info(
                            f"CONVERSATION_MARKED_INACTIVE thread_id={thread_id} "
                            f"reason=no_reply_after_{follow_up_count}_followups "
                            f"days_silent={days_silent:.1f}"
                        )
                    continue

                # Warm lead: landlord engaged then went quiet (e.g. after we
                # asked for their number) and there's nothing new to answer.
                # Nudge on a slower cadence instead of leaving it to decay.
                if (
                    latest_landlord_message
                    and not conversation.phone_found
                    and conversation.status != INACTIVE_NO_REPLY
                ):
                    last_activity = (
                        conversation.last_outbound_at
                        or conversation.last_message_at
                        or conversation.created_at
                    )
                    days_silent = (
                        (datetime.utcnow() - last_activity).total_seconds() / 86400
                        if last_activity else 0
                    )
                    warm_count = conversation.follow_up_count or 0

                    if days_silent < WARM_FOLLOW_UP_INTERVAL_DAYS:
                        update_conversation_status(thread_id, SKIPPED)
                    elif warm_count == 0 and days_silent > WARM_FOLLOW_UP_STALE_DAYS:
                        # Long-dormant thread we never nudged (existing backlog).
                        # Leave it untouched rather than cold-poking a stale lead.
                        logger.info(
                            f"WARM_FOLLOW_UP_SKIPPED_STALE thread_id={thread_id} "
                            f"days_silent={days_silent:.1f}"
                        )
                        update_conversation_status(thread_id, SKIPPED)
                    elif warm_count < WARM_FOLLOW_UP_MAX:
                        follow_up_msg, err = generate_follow_up_message(
                            messages, follow_up_number=warm_count + 1
                        )
                        if follow_up_msg:
                            sent = await send_reply(page, follow_up_msg)
                            if sent:
                                save_message(thread_id, "outbound", follow_up_msg)
                                new_count = increment_follow_up_count(thread_id)
                                logger.info(
                                    f"WARM_FOLLOW_UP_SENT thread_id={thread_id} "
                                    f"number={new_count} days_silent={days_silent:.1f}"
                                )
                            else:
                                still_open = await can_reply(page)
                                if not still_open:
                                    update_conversation_status(thread_id, REPLY_DISABLED)
                                logger.warning(
                                    f"WARM_FOLLOW_UP_SEND_FAILED thread_id={thread_id}"
                                )
                        else:
                            logger.warning(
                                f"WARM_FOLLOW_UP_GENERATION_FAILED thread_id={thread_id} error={err}"
                            )
                    else:
                        mark_conversation_inactive(thread_id)
                        logger.info(
                            f"WARM_CONVERSATION_MARKED_INACTIVE thread_id={thread_id} "
                            f"reason=no_reply_after_{warm_count}_warm_followups "
                            f"days_silent={days_silent:.1f}"
                        )
                    continue

                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    "reason=no_unanswered_landlord_message"
                )
                update_conversation_status(thread_id, SKIPPED)
                continue

            decision = post_capture_decision(conversation)
            if decision is not None:
                # P1: objective already met (landlord number captured). Stop the
                # post-capture reply spiral that triggers "you keep messaging /
                # are you a bot" reports. Any due viewing cancellation is handled
                # above; a booked viewing still awaiting its cancel window stays
                # non-terminal so that cancellation can still fire on a later run.
                update_last_processed_message(thread_id, latest_landlord_message)
                if decision == "terminal":
                    mark_handoff_complete(thread_id)
                    update_conversation_status(thread_id, HANDOFF_COMPLETE)
                    logger.info(
                        f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                        "reason=phone_already_captured action=handoff_complete"
                    )
                else:
                    logger.info(
                        f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                        "reason=phone_captured_awaiting_cancellation"
                    )
                continue

            logger.info(f"THREAD_PROCESSING thread_id={thread_id}")

            landlord_messages = get_landlord_messages(
                messages
            )

            landlord_texts = landlord_messages

            persona = ensure_account_persona(account.id)
            landlord_attitude = detect_landlord_attitude(
                messages,
                previous=conversation.landlord_attitude if conversation else None,
            )
            conversation_style = (
                conversation.conversation_style
                if conversation and conversation.conversation_style
                else persona.get("conversation_style")
            )
            landlord_asked_number = latest_landlord_asked_for_phone(messages)
            landlord_hesitant = latest_landlord_hesitant_about_phone(messages)

            update_conversation_memory(
                thread_id,
                landlord_attitude=landlord_attitude,
                conversation_style=conversation_style,
            )
            if landlord_asked_number:
                mark_landlord_asked_phone(thread_id)

            await close_verified_tenant_popup(page)

            phone = regex_extract_phone(
                landlord_texts
            )
            if not phone:

                revealed = await reveal_hidden_phone_number(page)

                if revealed:

                    messages = await extract_conversation(page)

                    landlord_messages = get_landlord_messages(
                        messages
                    )

                    landlord_texts = landlord_messages

                    phone = regex_extract_phone(
                        landlord_texts
                    )
            # Fallback to AI extraction
            if not phone:


                await close_verified_tenant_popup(page)

                phone = ai_extract_phone(
                    landlord_texts
                )
                if phone:

                    logger.info(f"AI Phone found: {phone}")
                    update_conversation_status(thread_id, PHONE_ACQUIRED)
                    phone = normalize_uk_phone(phone)

                    if not phone:
                        # normalise stripped all digits (e.g. "(Number Removed)") —
                        # not a real UK number; never overwrite a stored phone with empty
                        logger.warning(
                            f"PHONE_NORMALISE_EMPTY thread_id={thread_id} "
                            "AI extraction returned non-numeric text — ignoring"
                        )
                        await _screenshot_thread(page, thread_id, label="number_removed_ai")
                        update_last_processed_message(thread_id, latest_landlord_message)
                        continue

                    stored_phone = conversation.extracted_phone if conversation else None

                    if stored_phone and stored_phone == phone:
                        logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone} status=already_known")
                        update_last_processed_message(thread_id, latest_landlord_message)
                        continue

                    if stored_phone and stored_phone != phone:
                        if phone_exists(phone):
                            logger.info(
                                f"PHONE_REPLACE_DUPLICATE thread_id={thread_id} "
                                f"phone={phone} owned_by_other_conversation"
                            )
                            await _send_duplicate_close(
                                thread_id, conversation, messages, page, _was_duplicate
                            )
                            update_conversation_status(thread_id, DUPLICATE_LEAD)
                            update_last_processed_message(thread_id, latest_landlord_message)
                            continue
                        logger.info(
                            f"PHONE_REPLACED thread_id={thread_id} "
                            f"OLD_PHONE={stored_phone} NEW_PHONE={phone}"
                        )
                        save_phone_number(thread_id, phone)
                        _log_playbook_ab_phone_capture(thread_id)
                        update_last_processed_message(thread_id, latest_landlord_message)
                        continue

                    if phone_exists(phone):
                        logger.info(f"Duplicate phone detected: {phone}")
                        await _send_duplicate_close(
                            thread_id, conversation, messages, page, _was_duplicate
                        )
                        update_conversation_status(thread_id, DUPLICATE_LEAD)
                        continue

                    logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone}")
                    save_phone_number(thread_id, phone)
                    _log_playbook_ab_phone_capture(thread_id)

                    # Try to extract viewing datetime from messages and apply the
                    # 3–5h cancellation window strategy.
                    saved_dt = await _try_save_viewing_datetime(thread_id, messages)
                    if saved_dt:
                        fresh2 = get_conversation_by_thread_id(thread_id)
                        viewing_dt = getattr(fresh2, "viewing_datetime", None)
                        if _cancel_window_passed(viewing_dt):
                            reason = "no_datetime" if viewing_dt is None else f"window_passed"
                            logger.info(f"VIEWING_CANCEL_NOW thread_id={thread_id} trigger=phone_found reason={reason}")
                            cancelled = await _cancel_viewing_and_handoff(
                                thread_id, messages, latest_landlord_message, page
                            )
                            if not cancelled:
                                logger.warning(f"VIEWING_CANCEL_FAILED thread_id={thread_id}")
                        else:
                            hours_until = (viewing_dt - datetime.utcnow()).total_seconds() / 3600
                            logger.info(
                                f"VIEWING_CANCEL_DEFERRED thread_id={thread_id} "
                                f"hours_until={hours_until:.1f} trigger=phone_found"
                            )
                            update_last_processed_message(thread_id, latest_landlord_message)
                    else:
                        inline_stage = detect_stage(messages)
                        if inline_stage == "VIEWING_BOOKED":
                            update_conversation_stage(thread_id, VIEWING_PENDING)
                        elif inline_stage:
                            update_conversation_stage(thread_id, inline_stage)
                        logger.info(
                            f"PHONE_OBTAINED thread_id={thread_id} viewing=False — deferred to reminder"
                        )
                        update_last_processed_message(thread_id, latest_landlord_message)

                    phones_today = count_phones_today(account.id)
                    if phones_today >= 3:
                        logger.info(
                            f"Daily phone target reached for {account.email}: {phones_today}/3"
                        )
                    continue

            if phone:

                logger.info(f"Phone found: {phone}")
                update_conversation_status(thread_id, PHONE_ACQUIRED)
                phone = normalize_uk_phone(phone)

                if not phone:
                    logger.warning(
                        f"PHONE_NORMALISE_EMPTY thread_id={thread_id} "
                        "regex extraction returned non-numeric text — ignoring"
                    )
                    await _screenshot_thread(page, thread_id, label="number_removed_regex")
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

                stored_phone = conversation.extracted_phone if conversation else None

                if stored_phone and stored_phone == phone:
                    logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone} status=already_known")
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

                if stored_phone and stored_phone != phone:
                    logger.info(
                        f"PHONE_REPLACED thread_id={thread_id} "
                        f"OLD_PHONE={stored_phone} NEW_PHONE={phone}"
                    )
                    save_phone_number(thread_id, phone)
                    _log_playbook_ab_phone_capture(thread_id)
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

                if phone_exists(phone):
                    logger.info(f"Duplicate phone detected: {phone}")
                    await _send_duplicate_close(
                        thread_id, conversation, messages, page, _was_duplicate
                    )
                    update_conversation_status(thread_id, DUPLICATE_LEAD)
                    continue

                logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone}")
                save_phone_number(thread_id, phone)
                _log_playbook_ab_phone_capture(thread_id)

                saved_dt = await _try_save_viewing_datetime(thread_id, messages)
                if saved_dt:
                    fresh2 = get_conversation_by_thread_id(thread_id)
                    viewing_dt = getattr(fresh2, "viewing_datetime", None)
                    if _cancel_window_passed(viewing_dt):
                        reason = "no_datetime" if viewing_dt is None else "window_passed"
                        logger.info(f"VIEWING_CANCEL_NOW thread_id={thread_id} trigger=phone_found reason={reason}")
                        cancelled = await _cancel_viewing_and_handoff(
                            thread_id, messages, latest_landlord_message, page,
                            persona=persona,
                        )
                        if not cancelled:
                            logger.warning(f"VIEWING_CANCEL_FAILED thread_id={thread_id}")
                    else:
                        hours_until = (viewing_dt - datetime.utcnow()).total_seconds() / 3600
                        logger.info(
                            f"VIEWING_CANCEL_DEFERRED thread_id={thread_id} "
                            f"hours_until={hours_until:.1f} trigger=phone_found"
                        )
                        update_last_processed_message(thread_id, latest_landlord_message)
                else:
                    inline_stage = detect_stage(messages)
                    if inline_stage == "VIEWING_BOOKED":
                        update_conversation_stage(thread_id, VIEWING_PENDING)
                    elif inline_stage:
                        update_conversation_stage(thread_id, inline_stage)
                    logger.info(
                        f"PHONE_OBTAINED thread_id={thread_id} viewing=False — deferred to reminder"
                    )
                    update_last_processed_message(thread_id, latest_landlord_message)

                phones_today = count_phones_today(account.id)
                if phones_today >= 3:
                    logger.info(
                        f"Daily phone target reached for {account.email}: {phones_today}/3"
                    )
                continue
            
            
                
            # VIEWING_BOOKED is only ever set by:
            #   1. The OpenRent "Viewing Confirmed" banner (most reliable)
            #   2. ai_detect_viewing_arranged() when no banner is present (lines ~545)
            # Regex-based detect_stage is intentionally NOT used for VIEWING_BOOKED
            # because it false-positives on phrases like "that works" or bare numbers
            # like "1 bed flat". Only non-booking stages are updated here.
            stage = detect_stage(messages)
            # Do NOT let a regex stage downgrade clobber a genuinely-confirmed
            # viewing. viewing_confirmed (banner / AI-detect) is authoritative; a
            # later chatty message that regex-classifies as DISCUSSION/PENDING must
            # not move the persisted stage off its booked state. That drift
            # (viewing_confirmed=True while stage=VIEWING_DISCUSSION) is what used to
            # drop confirmed viewings out of the cancellation sweep. Reply
            # generation below still uses the freshly-detected `stage` regardless.
            if (
                stage
                and stage != VIEWING_BOOKED
                and not (conversation and getattr(conversation, "viewing_confirmed", False))
            ):
                if stage == VIEWING_PENDING:
                    logger.info(
                        f"VIEWING_PENDING thread_id={thread_id} "
                        "reason=vague_viewing_promise no_specific_time"
                    )
                update_conversation_stage(thread_id, stage)

            if not should_ai_reply(messages):
                logger.info(f"No AI reply needed for thread {thread_id}")
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    "reason=latest_message_not_landlord"
                )
                update_conversation_status(thread_id, SKIPPED)
                continue

            reply_allowed = await can_reply(
                page
            )

            if not reply_allowed:

                logger.warning(f"Reply disabled for thread {thread_id}")

                update_conversation_status(
                    thread_id,
                    REPLY_DISABLED
                )
                update_last_processed_message(
                    thread_id,
                    latest_landlord_message
                )

                continue

            # Short-term property guard: if the landlord has explicitly stated
            # this is a short-term / holiday let (<12 months), send a polite
            # closing reply and permanently mark the conversation.
            if detect_short_term_tenancy(messages):
                logger.info(
                    f"SHORT_TERM_PROPERTY detected thread_id={thread_id} "
                    "— sending polite close and marking conversation"
                )
                _close_msg, _close_err = generate_short_term_close_message(messages)
                if _close_msg:
                    _close_sent = await send_reply(page, _close_msg)
                    if _close_sent:
                        save_message(thread_id, "outbound", _close_msg)
                    else:
                        logger.warning(
                            f"SHORT_TERM_CLOSE_SEND_FAILED thread_id={thread_id}"
                        )
                else:
                    logger.warning(
                        f"SHORT_TERM_CLOSE_GENERATE_FAILED thread_id={thread_id} "
                        f"error={_close_err}"
                    )
                update_conversation_status(thread_id, SHORT_TERM_PROPERTY)
                update_conversation_stage(thread_id, SHORT_TERM_PROPERTY)
                update_last_processed_message(thread_id, latest_landlord_message)
                continue

            # OPEN-21D playbook A/B: assign + log BEFORE any automated reply path.
            # No-op unless PLAYBOOK_AB_ENABLED=1.
            ab_assignment = _assign_playbook_ab_if_enabled(thread_id, persona)

            name_reply = (
                _build_name_reply(persona)
                if _is_name_question(latest_landlord_message)
                else None
            )

            if name_reply:
                logger.info(
                    f"Name question detected for thread {thread_id}; "
                    "using persona name reply"
                )
                save_ai_reply(thread_id, name_reply)
                sent = await send_reply(page, name_reply)
                if not sent:
                    logger.warning(f"Name reply send failed for thread {thread_id}")
                    update_conversation_status(thread_id, AI_FAILED)
                    continue

                logger.info("Reply sent")
                save_message(thread_id, "outbound", name_reply)
                update_last_processed_message(thread_id, latest_landlord_message)
                update_conversation_status(thread_id, AI_REPLIED)
                logger.info("Reply pipeline completed")
                continue

            # --- Video-call / screening-call gate ------------------------
            # Some landlords require a live video/screening call (Zoom/Meet/
            # Teams) before an in-person viewing. We cannot attend a call, and
            # agreeing to one produces a no-show + fabricated-excuse loop that
            # burns the account (e.g. thread 45936155). Pivot to our WhatsApp
            # give-out instead: hand the number over once so a WhatsApp inbound
            # captures the landlord as a lead, then stop agreeing to calls. If
            # we already shared our number, disengage rather than loop.
            _no_phone_yet = not (
                conversation and getattr(conversation, "extracted_phone", None)
            )
            if _no_phone_yet and landlord_wants_video_call(messages):
                if conversation and getattr(conversation, "our_number_shared_at", None):
                    logger.info(
                        f"VIDEO_CALL_GIVEOUT_ALREADY_SHARED thread_id={thread_id} "
                        "- not re-agreeing to a call; awaiting WhatsApp/new info"
                    )
                    update_last_processed_message(thread_id, latest_landlord_message)
                    update_conversation_status(thread_id, AI_REPLIED)
                    continue
                giveout_sent = await _try_giveout_salvage(
                    thread_id, conversation, account, messages,
                    latest_landlord_message, page,
                    require_landlord_asked=False,
                )
                if giveout_sent:
                    logger.info(f"VIDEO_CALL_GIVEOUT_SENT thread_id={thread_id}")
                    update_conversation_status(thread_id, AI_REPLIED)
                else:
                    logger.info(
                        f"VIDEO_CALL_GIVEOUT_NOT_SENT thread_id={thread_id} "
                        "- skipping run rather than agreeing to a call"
                    )
                continue
            # -------------------------------------------------------------

            logger.info(
                f"Generating AI reply for thread {thread_id} "
                f"at stage {stage or 'NEW_REPLY'}"
            )

            # Resolve the travel city for all stages so the tenant's origin
            # location is consistent throughout the entire conversation.
            property_location = get_thread_property_location(thread_id)
            travel_city = get_travel_city(thread_id)
            if travel_city:
                logger.info(
                    f"TRAVEL_CITY_REUSED thread_id={thread_id} city={travel_city}"
                )
            elif property_location:
                travel_city = generate_distant_location(property_location)
                save_travel_city(thread_id, travel_city)
                logger.info(
                    f"TRAVEL_CITY_ASSIGNED thread_id={thread_id} city={travel_city}"
                )

            ab_design = (
                ab_assignment["assigned_design_id"]
                if ab_assignment
                else None
            )

            # Arm B (landlord-number-capture designs) must NOT have the tenant mobile injected by
            # the safeguard below - that would re-add the number the playbook withholds. For arm A
            # / flag-off, ab_design is None -> True -> exact current behaviour.
            ab_expose_mobile = ab_design not in playbook_ab.LANDLORD_NUMBER_CAPTURE_DESIGNS

            reply, error = generate_reply(
                messages,
                stage=stage,
                persona=persona,
                property_location=property_location,
                conversation=conversation,
                conversation_design_id=ab_design,
                landlord_attitude=landlord_attitude,
                conversation_style=conversation_style,
                travel_city=travel_city,
                thread_id=thread_id,
            )

            if not reply or error:

                logger.error(
                    f"AI reply generation failed for thread {thread_id}: "
                    f"{error or 'empty_reply'}"
                )

                update_conversation_status(
                    thread_id,
                    AI_FAILED
                )

                # Loop-breaker: invalid_ai_reply means the model produced a reply
                # we rejected (e.g. an unanswerable ask that becomes a "[surname]"
                # placeholder). Re-attempting the identical message every run just
                # fails again forever (the thread 45914242 full-name loop). Ack the
                # message so we only retry once the landlord says something new.
                # Transient/empty errors are left un-acked so they still retry.
                if error == "invalid_ai_reply" and latest_landlord_message:
                    update_last_processed_message(thread_id, latest_landlord_message)

                continue

            mobile = persona.get("mobile_number") if persona else None

            # Detect screening questions so we can decide whether to inject
            # the phone number.  When the landlord asked screening questions
            # (name, job, income, etc.) the AI must answer them first; forcing
            # the phone number into that reply suppresses the actual answers.
            screening_questions = detect_screening_questions(messages)
            if screening_questions:
                logger.info(
                    f"LANDLORD_QUESTION_DETECTED thread_id={thread_id}"
                    f" QUESTION_COUNT={len(screening_questions)}"
                    f" topics={screening_questions}"
                )

            # Landlord phone safeguard: always remove hallucinated numbers,
            # but only inject the tenant mobile when there are NO pending
            # screening questions.  If questions are present, the AI was
            # already instructed to answer them first; injecting a number here
            # would override that answer with a phone line.
            # Only share our WhatsApp number when BOTH conditions are true:
            # 1. Landlord explicitly asked for our number
            # 2. Landlord is unwilling to share their own number
            # Never share if we already received the landlord's number.
            landlord_already_gave_number = bool(
                conversation and getattr(conversation, "phone_found", False)
            )
            # Last resort only: we must have already asked for the landlord's
            # own number in this conversation before we ever volunteer ours.
            we_already_asked_for_their_number = count_number_asks(messages) >= 1
            should_share_our_number = (
                landlord_asked_number
                and landlord_hesitant
                and not landlord_already_gave_number
                and we_already_asked_for_their_number
            )
            if should_share_our_number or landlord_asked_number or landlord_hesitant:
                before_safeguard = reply
                reply = remove_unapproved_phone_numbers(reply, mobile)

                if (
                    should_share_our_number
                    and mobile
                    and mobile not in reply
                    and not screening_questions
                    and ab_expose_mobile
                ):
                    whatsapp_line = (
                        f"My husband's WhatsApp is {mobile}, "
                        "he handles the viewing coordination, so best to reach him there."
                    )
                    reply = f"{reply.rstrip()} {whatsapp_line}" if reply else whatsapp_line

                logger.info(
                    f"Phone safeguard applied for thread {thread_id}; "
                    f"mobile_assigned={bool(mobile)}; "
                    f"landlord_asked={landlord_asked_number}; "
                    f"landlord_hesitant={landlord_hesitant}; "
                    f"screening_questions_present={bool(screening_questions)}; "
                    f"changed={before_safeguard != reply}"
                )

            if screening_questions:
                answered_count = sum(
                    1 for topic in screening_questions
                    if topic.lower() in reply.lower()
                    or (topic == "name" and bool(
                        (persona or {}).get("persona_name", "").lower() in reply.lower()
                    ))
                    or (topic == "income" and any(c in reply for c in ("£", "$", "k ", "k,")))
                )
                if answered_count >= len(screening_questions):
                    logger.info(
                        f"QUESTION_RESPONSE_VALIDATION thread_id={thread_id}"
                        f" ANSWERED_COUNT={answered_count}/{len(screening_questions)}"
                    )
                else:
                    logger.warning(
                        f"QUESTION_RESPONSE_VALIDATION_FAILED thread_id={thread_id}"
                        f" ANSWERED_COUNT={answered_count}/{len(screening_questions)}"
                        f" topics_missing={[t for t in screening_questions if t.lower() not in reply.lower()]}"
                    )

            if not reply:
                logger.warning(
                    f"Reply became empty after phone safeguards for thread {thread_id}"
                )
                update_conversation_status(thread_id, AI_FAILED)
                continue

            logger.info(
                f"AI reply generated for thread {thread_id}: {reply}"
            )

            # Persistence stage: always store the generated reply so the
            # dashboard can show review-mode and failed-send drafts.
            save_ai_reply(
                thread_id,
                reply
            )

            sent = await send_reply(
                page,
                reply
            )
            if not sent:
                # If the textarea/button became disabled between our can_reply()
                # check and the actual send, classify as REPLY_DISABLED rather
                # than AI_FAILED so the thread isn't retried unnecessarily.
                still_open = await can_reply(page)
                if not still_open:
                    logger.warning(
                        f"Reply disabled for thread {thread_id} "
                        "(detected at send time — textarea or button became disabled)"
                    )
                    update_conversation_status(thread_id, REPLY_DISABLED)
                else:
                    logger.warning(f"Reply send failed for thread {thread_id}")
                    update_conversation_status(thread_id, AI_FAILED)
                continue

            logger.info("Reply sent")
            save_message(thread_id, "outbound", reply)
            logger.info(f"Outbound reply persisted for thread {thread_id}")

            # Track when we share our WhatsApp number with the landlord
            if mobile and tenant_shared_phone(
                [{"sender": "outbound", "message": reply}], mobile
            ):
                mark_our_number_shared(thread_id)
                logger.info(f"OUR_NUMBER_SHARED thread_id={thread_id}")

            # OPEN-21D playbook A/B - append-only HEURISTIC outcome diagnostics. No-op unless
            # enabled; wrapped so it can NEVER affect reply behaviour. NOT the primary outcome:
            # qualified_landlord_phone_capture is graded ARM-BLIND by the frozen v2 grader.
            if os.getenv("PLAYBOOK_AB_ENABLED") == "1":
                try:
                    playbook_ab.log_outcome(
                        thread_id,
                        os.getenv("PLAYBOOK_AB_OUTCOME_LOG", "logs/playbook_ab_outcomes.jsonl"),
                        event="reply_sent",
                        reply_received=bool(landlord_texts),
                        landlord_phone_captured=None,
                        landlord_number_requested=playbook_ab.asks_for_landlord_number(reply),
                        tenant_number_given_first=bool(mobile and mobile in reply and not phone),
                        conversation_progressed=(stage == "VIEWING_BOOKED"),
                        parked_or_dropped=None,
                        unsafe_or_pushy_detected=None,
                    )
                except Exception as _ab_e:
                    logger.warning(
                        f"PLAYBOOK_AB outcome log failed thread_id={thread_id}: {_ab_e}"
                    )

            # Conversation status updates: move metadata forward after a valid
            # reply is generated and sent.
            update_last_processed_message(thread_id, latest_landlord_message)

            if stage == "VIEWING_BOOKED" and not landlord_asked_number:
                if conversation and conversation.phone_requested_at:
                    logger.info(
                        f"Phone already requested for thread {thread_id} "
                        f"(requested at {conversation.phone_requested_at})"
                    )
                else:
                    mark_phone_requested(thread_id)
                    logger.info(
                        f"Phone number request sent for thread {thread_id}"
                    )
            if mobile and mobile in reply:
                mark_phone_number_shared(thread_id)

            update_conversation_status(thread_id, AI_REPLIED)
            logger.info("Reply pipeline completed")
            logger.info(
                f"Reply pipeline completed for thread {thread_id}; "
                f"sent={sent}"
            )

        except Exception as e:

            logger.exception(f"Failed processing thread {thread_id}: {e}")
            if thread_id:
                update_conversation_status(thread_id, AI_FAILED)
            report_error(
                "messaging",
                "Reply processing failed",
                context={"thread_id": thread_id, "account_id": account.id},
                exc=e,
            )
        finally:
            if thread_id:
                release_conversation_claim(
                    thread_id,
                    worker_id or f"account-{account.id}"
                )
