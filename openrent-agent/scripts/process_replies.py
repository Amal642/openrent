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
    update_last_processed_message,
    phone_exists,
    mark_handoff_complete,
    mark_phone_requested,
    mark_phone_number_shared,
    mark_landlord_asked_phone,
    update_conversation_memory,
    save_viewing_datetime,
    save_banner_state,
    count_phones_today,
    get_thread_property_location,
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
)

from app.ai.extractors import (
    ai_extract_phone,
    regex_extract_phone
)

from app.ai.replies import (
    generate_handoff_message,
    generate_reply
)

from app.ai.validators import (
    remove_unapproved_phone_numbers
)

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    latest_landlord_asked_for_phone,
)

from app.utils.phone import (
    normalize_uk_phone
)
from app.utils.logger import logger

from app.db.status import (
    SKIPPED,
    PHONE_ACQUIRED,
    DUPLICATE_LEAD,
    REPLY_DISABLED,
    AI_FAILED,
    AI_REPLIED,
    HANDOFF_COMPLETE,
    VIEWING_PENDING,
)

from datetime import datetime, timezone
import re


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


# Fixed message sent once both a phone number and a confirmed viewing are on record.
_BOOKING_HANDOFF_MSG = (
    "Thanks for sharing your number, I'll be in touch as we get closer to the viewing."
)


async def _send_handoff_message(thread_id, messages, latest_landlord_message, page, message=None):
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
        logger.warning(f"Handoff message send failed for thread {thread_id}")
        return False

    logger.info("HANDOFF MESSAGE SENT")
    save_message(thread_id, "outbound", handoff_message)
    update_last_processed_message(thread_id, latest_landlord_message)
    mark_handoff_complete(thread_id)
    logger.info(f"HANDOFF_COMPLETE thread_id={thread_id}")
    logger.info("CONVERSATION HANDOFF COMPLETE")
    return True

async def process_account_replies(
    account,
    page,
    worker_id=None
):



    threads = await get_all_reply_threads(page)

    print(
        f"\nFound {len(threads)} "
        f"reply threads\n"
    )
    logger.info(f"Found {len(threads)} reply threads")

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
            if banners["viewing_confirmed"] and banners["viewing_datetime"]:
                save_banner_state(
                    thread_id,
                    viewing_requested=banners["viewing_requested"],
                    viewing_confirmed=True,
                    viewing_datetime=banners["viewing_datetime"],
                )
            elif banners["viewing_requested"]:
                save_banner_state(thread_id, viewing_requested=True)

            save_inbound_messages(thread_id, messages)

            conversation = (
                get_conversation_by_thread_id(
                    thread_id
                )
            )

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

            if (
                conversation
                and
                conversation.conversation_stage
                ==
                HANDOFF_COMPLETE
            ):
                logger.info(
                    "Conversation handed off. "
                    "Skipping AI responses."
                )
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    "reason=handoff_complete"
                )
                update_last_processed_message(thread_id, latest_landlord_message)
                continue

            # Post-booking handoff: fire once viewing is confirmed (via banner)
            # and the landlord's phone number is already on file.
            if (
                conversation
                and conversation.viewing_confirmed
                and conversation.phone_found
                and not conversation.handoff_completed_at
            ):
                logger.info(
                    f"HANDOFF_COMPLETE trigger=viewing_confirmed+phone_found "
                    f"thread_id={thread_id}"
                )
                handoff_sent = await _send_handoff_message(
                    thread_id,
                    messages,
                    latest_landlord_message,
                    page,
                    message=_BOOKING_HANDOFF_MSG,
                )
                if handoff_sent:
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

            if (
                conversation
                and
                conversation.last_processed_message
                ==
                latest_landlord_message
                and not has_unanswered_landlord_message
            ):

                print(
                    "\nNo new landlord activity. "
                    "Skipping thread."
                )
                logger.info(
                    f"THREAD_SKIPPED_REASON thread_id={thread_id} "
                    "reason=no_unanswered_landlord_message"
                )
                logger.info(f"No new landlord activity for thread {thread_id}. Skipping.")
                update_conversation_status(thread_id, SKIPPED)
                continue

            print(
                f"\nTHREAD {thread_id}"
            )
            logger.info(f"Processing thread {thread_id}")

            for msg in messages:

                print(
                    f"[{msg['sender']}] "
                    f"{msg['message']}"
                )
                logger.info(f"[{msg['sender']}] {msg['message']}")

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

                    print(
                        f"\nAI PHONE FOUND: {phone}"
                    )
                    logger.info(f"AI Phone found: {phone}")
                    logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone}")
                    update_conversation_status(thread_id, PHONE_ACQUIRED)   
                    phone = normalize_uk_phone(
                        phone
                    )
                    if (
                        conversation
                        and conversation.extracted_phone == phone
                        and conversation.conversation_stage != HANDOFF_COMPLETE
                    ):
                        if conversation.viewing_confirmed and not conversation.handoff_completed_at:
                            handoff_sent = await _send_handoff_message(
                                thread_id, messages, latest_landlord_message, page,
                                message=_BOOKING_HANDOFF_MSG,
                            )
                            if not handoff_sent:
                                continue
                        else:
                            logger.info(
                                f"PHONE_OBTAINED thread_id={thread_id} "
                                "viewing_confirmed=False — handoff deferred"
                            )
                            update_last_processed_message(thread_id, latest_landlord_message)
                        continue

                    if phone_exists(phone):

                        print(
                            "\nDuplicate phone detected"
                        )
                        logger.info(f"Duplicate phone detected: {phone}")

                        update_conversation_status(
                            thread_id,
                            DUPLICATE_LEAD
                        )

                        continue

                    save_phone_number(thread_id, phone)
                    logger.info(f"PHONE_OBTAINED thread_id={thread_id}")
                    fresh = get_conversation_by_thread_id(thread_id)
                    if fresh and fresh.viewing_confirmed and not fresh.handoff_completed_at:
                        handoff_sent = await _send_handoff_message(
                            thread_id, messages, latest_landlord_message, page,
                            message=_BOOKING_HANDOFF_MSG,
                        )
                        if not handoff_sent:
                            continue
                        logger.info(f"PHONE_NUMBER_EXTRACTED+viewing_confirmed handoff sent thread_id={thread_id}")
                    else:
                        logger.info(
                            f"PHONE_OBTAINED thread_id={thread_id} "
                            "viewing_confirmed=False — handoff deferred"
                        )
                        update_last_processed_message(thread_id, latest_landlord_message)
                    phones_today = count_phones_today(account.id)
                    if phones_today >= 3:
                        logger.info(
                            f"Daily phone target reached for {account.email}: {phones_today}/3"
                        )
                    continue

            if phone:

                print(
                    f"\nPHONE FOUND: {phone}"
                )
                logger.info(f"Phone found: {phone}")
                logger.info(f"PHONE_FOUND thread_id={thread_id} phone={phone}")
                update_conversation_status(thread_id, PHONE_ACQUIRED)
                phone = normalize_uk_phone(
                    phone
                )
                if (
                    conversation
                    and conversation.extracted_phone == phone
                    and conversation.conversation_stage != HANDOFF_COMPLETE
                ):
                    if conversation.viewing_confirmed and not conversation.handoff_completed_at:
                        handoff_sent = await _send_handoff_message(
                            thread_id, messages, latest_landlord_message, page,
                            message=_BOOKING_HANDOFF_MSG,
                        )
                        if not handoff_sent:
                            continue
                    else:
                        logger.info(
                            f"PHONE_OBTAINED thread_id={thread_id} "
                            "viewing_confirmed=False — handoff deferred"
                        )
                        update_last_processed_message(thread_id, latest_landlord_message)
                    continue

                if phone_exists(phone):

                    print(
                        "\nDuplicate phone detected"
                    )
                    logger.info(f"Duplicate phone detected: {phone}")

                    update_conversation_status(
                        thread_id,
                        DUPLICATE_LEAD
                    )

                    continue
                save_phone_number(thread_id, phone)
                logger.info(f"PHONE_OBTAINED thread_id={thread_id}")
                fresh = get_conversation_by_thread_id(thread_id)
                if fresh and fresh.viewing_confirmed and not fresh.handoff_completed_at:
                    handoff_sent = await _send_handoff_message(
                        thread_id, messages, latest_landlord_message, page,
                        message=_BOOKING_HANDOFF_MSG,
                    )
                    if not handoff_sent:
                        continue
                    logger.info(f"PHONE_NUMBER_EXTRACTED+viewing_confirmed handoff sent thread_id={thread_id}")
                else:
                    logger.info(
                        f"PHONE_OBTAINED thread_id={thread_id} "
                        "viewing_confirmed=False — handoff deferred until viewing confirmed"
                    )
                    update_last_processed_message(thread_id, latest_landlord_message)
                phones_today = count_phones_today(account.id)
                if phones_today >= 3:
                    logger.info(
                        f"Daily phone target reached for {account.email}: {phones_today}/3"
                    )
                continue
            
            
                
            stage = detect_stage(
                messages
            )

            if stage:

                print(
                    f"Detected stage: {stage}"
                )

                if stage == "VIEWING_BOOKED":
                    viewing_datetime = extract_viewing_datetime(messages)
                    if viewing_datetime:
                        save_viewing_datetime(thread_id, viewing_datetime)
                        logger.info(
                            f"VIEWING_BOOKED_SET thread_id={thread_id} "
                            f"viewing_datetime={viewing_datetime}"
                        )
                    else:
                        # Stage signal seen but no confirmed date+time — record
                        # as pending so cancellation logic cannot trigger.
                        logger.warning(
                            f"VIEWING_PENDING thread_id={thread_id} "
                            "reason=no_confirmed_datetime stage_signal=VIEWING_BOOKED"
                        )
                        update_conversation_stage(thread_id, VIEWING_PENDING)
                elif stage == VIEWING_PENDING:
                    logger.info(
                        f"VIEWING_PENDING thread_id={thread_id} "
                        "reason=vague_viewing_promise no_specific_time"
                    )
                    update_conversation_stage(thread_id, VIEWING_PENDING)
                else:
                    update_conversation_stage(thread_id, stage)

            if not should_ai_reply(messages):
                print("\nNo reply needed")
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

                print(
                    "\nReply disabled for thread"
                )
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

            # Reply generation stage: use the full conversation, stage memory,
            # persona, and landlord attitude to produce a natural response.
            print("\nGenerating AI reply...")
            logger.info(
                f"Generating AI reply for thread {thread_id} "
                f"at stage {stage or 'NEW_REPLY'}"
            )

            reply, error = generate_reply(
                messages,
                stage=stage,
                persona=persona,
                property_location=get_thread_property_location(thread_id),
                conversation=conversation,
                landlord_attitude=landlord_attitude,
                conversation_style=conversation_style,
            )

            if not reply or error:

                print("\nAI reply generation failed")
                logger.error(
                    f"AI reply generation failed for thread {thread_id}: "
                    f"{error or 'empty_reply'}"
                )

                update_conversation_status(
                    thread_id,
                    AI_FAILED
                )

                continue

            mobile = persona.get("mobile_number") if persona else None

            # Landlord phone safeguard stage: remove any hallucinated numbers,
            # then inject only the assigned tenant mobile when one exists.
            if landlord_asked_number:
                before_safeguard = reply
                reply = remove_unapproved_phone_numbers(reply, mobile)

                if mobile and mobile not in reply:
                    reply = (
                        f"{reply.rstrip()} My number is {mobile}."
                        if reply
                        else f"My number is {mobile}."
                    )

                logger.info(
                    f"Phone safeguard applied for thread {thread_id}; "
                    f"mobile_assigned={bool(mobile)}; "
                    f"changed={before_safeguard != reply}"
                )

            if not reply:
                logger.warning(
                    f"Reply became empty after phone safeguards for thread {thread_id}"
                )
                update_conversation_status(thread_id, AI_FAILED)
                continue

            print("\nAI REPLY:")
            print(reply)
            logger.info("Reply generated")
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
                logger.warning(f"Reply send failed for thread {thread_id}")
                update_conversation_status(
                    thread_id,
                    AI_FAILED
                )
                continue

            logger.info("Reply sent")
            save_message(thread_id, "outbound", reply)
            logger.info(f"Outbound reply persisted for thread {thread_id}")

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

            print(
                "Failed processing thread:",
                e
            )
            logger.exception(f"Failed processing thread {thread_id}: {e}")
            if thread_id:
                update_conversation_status(thread_id, AI_FAILED)
        finally:
            if thread_id:
                release_conversation_claim(
                    thread_id,
                    worker_id or f"account-{account.id}"
                )
