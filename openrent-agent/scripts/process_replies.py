import asyncio

from app.db.repository import get_active_accounts

from app.browser.launcher import launch_browser
from app.browser.auth import login

from app.openrent.inbox import (
    get_all_reply_threads,
    get_landlord_messages,
    open_thread,
    extract_conversation,
    should_ai_reply
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


async def main():

    accounts = get_active_accounts()

    if not accounts:
        print("No accounts found")
        return

    account = accounts[0]

    playwright, browser, context, page = await launch_browser(account)

    try:

        await login(page, context, account)

        threads = await get_all_reply_threads(page)

        print(
            f"\nFound {len(threads)} "
            f"reply threads\n"
        )

        for thread in threads:

            try:

                thread_id = thread["thread_id"]

                await open_thread(page, thread_id)

                messages = await extract_conversation(page)

                print(
                    f"\nTHREAD {thread_id}"
                )

                for msg in messages:

                    print(
                        f"[{msg['sender']}] "
                        f"{msg['message']}"
                    )

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

                    continue
                # Fallback to AI extraction
                # Fallback to AI extraction
                if not phone:


                    phone = ai_extract_phone(
                        landlord_texts
                    )

                if should_ai_reply(messages):

                    print("\nGenerating AI reply...")

                    reply = generate_reply(
                        messages
                    )

                    print("\nAI REPLY:")
                    print(reply)

                    await send_reply(
                        page,
                        reply
                    )

                else:

                    print(
                        "\nNo reply needed"
                    )

            except Exception as e:

                print(
                    "Failed processing thread:",
                    e
                )

    finally:

        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())