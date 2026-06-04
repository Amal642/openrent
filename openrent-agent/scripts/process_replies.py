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
)


async def _send_handoff_message(thread_id, messages, latest_landlord_message, page):
    logger.info("PHONE NUMBER EXTRACTED")

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
                conversation.conversation_stage
                ==
                HANDOFF_COMPLETE
            ):
                logger.info(
                    "Conversation handed off. "
                    "Skipping AI responses."
                )
                update_last_processed_message(thread_id, latest_landlord_message)
                continue

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
                    if (
                        conversation
                        and conversation.extracted_phone == phone
                        and conversation.conversation_stage != HANDOFF_COMPLETE
                    ):
                        handoff_sent = await _send_handoff_message(
                            thread_id,
                            messages,
                            latest_landlord_message,
                            page,
                        )
                        if not handoff_sent:
                            continue
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
                    handoff_sent = await _send_handoff_message(
                        thread_id,
                        messages,
                        latest_landlord_message,
                        page,
                    )
                    if not handoff_sent:
                        continue
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
                if (
                    conversation
                    and conversation.extracted_phone == phone
                    and conversation.conversation_stage != HANDOFF_COMPLETE
                ):
                    handoff_sent = await _send_handoff_message(
                        thread_id,
                        messages,
                        latest_landlord_message,
                        page,
                    )
                    if not handoff_sent:
                        continue
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
                handoff_sent = await _send_handoff_message(
                    thread_id,
                    messages,
                    latest_landlord_message,
                    page,
                )
                if not handoff_sent:
                    continue
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
