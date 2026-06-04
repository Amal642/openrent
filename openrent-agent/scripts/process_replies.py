import random
from datetime import datetime, timedelta

from app.db.repository import (
    account_stop_requested,
    claim_conversation,
    clear_reply_due_at,
    ensure_account_persona,
    is_reply_due,
    release_conversation_claim,
    save_ai_reply,
    save_inbound_messages,
    save_message,
    save_phone_number,
    set_reply_due_at,
    update_conversation_stage,
    update_conversation_status,
    get_conversation_by_thread_id,
    update_last_processed_message,
    phone_exists,
    mark_phone_requested,
    mark_phone_number_shared,
    mark_landlord_asked_phone,
    update_conversation_memory,
    save_viewing_datetime,
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

from app.ai.stages import (
    detect_stage,
    extract_viewing_datetime,
)

from app.ai.extractors import (
    ai_extract_phone,
    regex_extract_phone
)

from app.ai.replies import (
    generate_reply
)

from app.ai.validators import (
    remove_unapproved_phone_numbers
)

from app.ai.conversation_memory import (
    detect_landlord_attitude,
    latest_landlord_asked_for_phone,
)

from app.utils.human import random_sleep

from app.config import settings

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
)

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
                logger.info(f"Thread {thread_id} already claimed. Skipping.")
                continue

            await open_thread(page, thread_id)

            messages = await extract_conversation(page)
            save_inbound_messages(thread_id, messages)

            latest_landlord_message = (
                get_latest_landlord_message(
                    messages
                )
            )

            conversation = (
                get_conversation_by_thread_id(
                    thread_id
                )
            )

            if (
                conversation
                and
                conversation.last_processed_message
                ==
                latest_landlord_message
            ):

                print(
                    "\nNo new landlord activity. "
                    "Skipping thread."
                )
                logger.info(f"No new landlord activity for thread {thread_id}. Skipping.")
                update_conversation_status(thread_id, SKIPPED)
                continue

            # ── Reply delay gate ──────────────────────────────────────
            # New landlord message detected.
            # If no delay has been set yet, generate one (20–50 min) and
            # skip this tick.  On subsequent ticks the check just waits.
            if conversation and not conversation.reply_due_at:
                delay_minutes = random.randint(20, 50)
                due_at = datetime.utcnow() + timedelta(minutes=delay_minutes)
                set_reply_due_at(thread_id, due_at)
                logger.info(
                    f"Reply delayed for thread {thread_id}: "
                    f"{delay_minutes} min (due at {due_at.strftime('%H:%M')} UTC)"
                )
                continue

            if not is_reply_due(thread_id):
                logger.info(
                    f"Reply not yet due for thread {thread_id} "
                    f"(due at {conversation.reply_due_at.strftime('%H:%M')} UTC)"
                )
                continue
            # ─────────────────────────────────────────────────────────

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


                phone = ai_extract_phone(
                    landlord_texts
                )
                if phone:

                    print(
                        f"\nAI PHONE FOUND: {phone}"
                    )
                    logger.info(f"AI Phone found: {phone}")
                    update_conversation_status(thread_id, PHONE_ACQUIRED)   
                    phone = normalize_uk_phone(
                        phone
                    )
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
                    logger.info(
                        f"Phone number acquired for thread {thread_id}: "
                        f"{phone} — marking conversation complete"
                    )
                    phones_today = count_phones_today(account.id)
                    if phones_today >= 3:
                        logger.info(
                            f"Daily phone target reached for {account.email}: {phones_today}/3"
                        )
                    update_last_processed_message(thread_id, latest_landlord_message)
                    continue

            if phone:

                print(
                    f"\nPHONE FOUND: {phone}"
                )
                logger.info(f"Phone found: {phone}")
                update_conversation_status(thread_id, PHONE_ACQUIRED)
                phone = normalize_uk_phone(
                    phone
                )
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
                # PHONE_ACQUIRED was already set above; add completion log here.
                logger.info(
                    f"Phone number acquired for thread {thread_id}: "
                    f"{phone} — marking conversation complete"
                )
                phones_today = count_phones_today(account.id)
                if phones_today >= 3:
                    logger.info(
                        f"Daily phone target reached for {account.email}: {phones_today}/3"
                    )
                update_last_processed_message(thread_id, latest_landlord_message)
                continue
            
            
                
            stage = detect_stage(
                messages
            )

            if stage:

                print(
                    f"Detected stage: {stage}"
                )

                update_conversation_stage(
                    thread_id,
                    stage
                )
                if stage == "VIEWING_BOOKED":
                    viewing_datetime = extract_viewing_datetime(messages)
                    if viewing_datetime:
                        save_viewing_datetime(thread_id, viewing_datetime)
                        logger.info(
                            f"Viewing booked for thread {thread_id} "
                            f"at {viewing_datetime}"
                        )

            if not should_ai_reply(messages):
                print("\nNo reply needed")
                logger.info(f"No AI reply needed for thread {thread_id}")
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
            logger.info(
                f"AI reply generated for thread {thread_id}: {reply}"
            )

            # Persistence stage: always store the generated reply so the
            # dashboard can show review-mode and failed-send drafts.
            save_ai_reply(
                thread_id,
                reply
            )

            await random_sleep(2, 5)

            sent = False

            # Autosend stage: only persist an outbound message after the
            # OpenRent send path reports success.
            if settings.AI_AUTOSEND:

                print("\nAUTO-SEND ENABLED")
                logger.info(f"Auto-send enabled for thread {thread_id}")

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

                save_message(thread_id, "outbound", reply)
                logger.info(f"Outbound reply persisted for thread {thread_id}")

            else:

                print(
                    "\nREVIEW MODE "
                    "(reply not sent)"
                )
                logger.info(f"Review mode enabled for thread {thread_id}")

            # Conversation status updates: move metadata forward after a valid
            # reply is generated, and after send when autosend is enabled.
            update_last_processed_message(thread_id, latest_landlord_message)
            clear_reply_due_at(thread_id)   # reset so next message gets a fresh delay

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
            logger.info(
                f"Reply pipeline completed for thread {thread_id}; "
                f"autosend={settings.AI_AUTOSEND}; sent={sent}"
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
