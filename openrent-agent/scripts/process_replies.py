from app.db.repository import (save_phone_number,save_ai_reply,update_conversation_status,get_conversation_by_thread_id,update_last_processed_message,phone_exists,update_landlord_scan,attach_landlord_to_listing,mark_listing_skipped_agent  )


from app.openrent.inbox import (
    get_all_reply_threads,
    get_landlord_messages,
    open_thread,
    extract_conversation,
    should_ai_reply,
    can_reply,
    get_latest_landlord_message
)

from app.ai.extractors import (
    ai_extract_phone,
    regex_extract_phone
)

from app.ai.replies import (
    generate_reply
)

from app.openrent.inbox import (
    send_reply
)

from app.utils.human import random_sleep

from app.config import settings

from app.utils.phone import (
    normalize_uk_phone
)
from app.utils.logger import logger

from app.utils.retry import (
    retry_async
)
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
    page
):



    threads = await get_all_reply_threads(page)

    print(
        f"\nFound {len(threads)} "
        f"reply threads\n"
    )
    logger.info(f"Found {len(threads)} reply threads")

    for thread in threads:

        try:

            thread_id = thread["thread_id"]

            await open_thread(page, thread_id)

            # profile_url = await extract_landlord_profile_url(page)

            # if profile_url:
            #     is_agent, count = await landlord_is_agent(page, profile_url, threshold=5)
            #     landlord = update_landlord_scan(profile_url, count, is_agent)
            #     attach_landlord_to_listing(thread_id, landlord.id)

            #     if is_agent:
            #         print(f"Skipping agent landlord ({count} properties): {profile_url}")
            #         mark_listing_skipped_agent(thread_id, count)
            #         continue

            messages = await extract_conversation(page)

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

            # if conversation and conversation.listing and conversation.listing.landlord and conversation.listing.landlord.is_agent:
            #     print(f"Skipping agent thread {thread_id}")
            #     continue

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


            phone = regex_extract_phone(
                landlord_texts
            )

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
                save_phone_number(
                    thread_id,
                    phone
                )
                update_last_processed_message(
                    thread_id,
                    latest_landlord_message
                )


                continue
            
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

                    save_phone_number(
                        thread_id,
                        phone
                    )

                    continue

            if should_ai_reply(messages):

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

                print("\nGenerating AI reply...")
                logger.info(f"Generating AI reply for thread {thread_id}")

                reply = generate_reply(
                    messages
                )
                if not reply:

                    print(
                        "\nAI reply generation failed"
                    )
                    logger.exception(f"AI reply generation failed for thread {thread_id}")

                    update_conversation_status(
                        thread_id,
                        AI_FAILED
                    )

                    continue

                print("\nAI REPLY:")
                print(reply)
                logger.info(f"AI reply generated for thread {thread_id} and the reply is {reply}")

                update_last_processed_message(
                    thread_id,
                    latest_landlord_message
                )
                await random_sleep(2, 5)

                if settings.AI_AUTOSEND:

                    print("\nAUTO-SEND ENABLED")
                    logger.info(f"Auto-send enabled for thread {thread_id}")

                    await send_reply(
                        page,
                        reply
                    )

                else:

                    print(
                        "\nREVIEW MODE "
                        "(reply not sent)"
                    )
                    logger.info(f"Review mode enabled for thread {thread_id}")

                save_ai_reply(
                    thread_id,
                    reply
                )

                update_conversation_status(thread_id, AI_REPLIED)
            else:

                print(
                    "\nNo reply needed"
                )
                update_conversation_status(thread_id, SKIPPED)

        except Exception as e:

            print(
                "Failed processing thread:",
                e
            )
            logger.exception(f"Failed processing thread {thread_id}: {e}")
            update_conversation_status(thread_id, AI_FAILED)

