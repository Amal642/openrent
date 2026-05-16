from datetime import (
    datetime,
    timedelta
)

from app.db.session import (
    session_scope
)

from app.models import (
    Conversation
)

from app.ai.replies import (
    generate_cancellation_message
)

from app.db.repository import (
    update_conversation_stage
)

from app.ai.replies import (
    send_reply
)


async def process_viewing_reminders():

    with session_scope() as db:

        now = datetime.utcnow()

        upcoming = db.query(
            Conversation
        ).filter(

            Conversation.viewing_datetime != None,

            Conversation.viewing_cancelled == False,

            Conversation.cancel_required == True

        ).all()

        for conversation in upcoming:

            viewing_time = (
                conversation.viewing_datetime
            )

            if not viewing_time:
                continue

            # cancel ~5hr before

            if (
                viewing_time - now
            ) <= timedelta(hours=5):

                try:

                    message = (
                        generate_cancellation_message()
                    )

                    await send_reply(
                        thread_id=conversation.thread_id,
                        message=message
                    )

                    conversation.viewing_cancelled = True

                    conversation.cancellation_sent_at = (
                        now
                    )

                    update_conversation_stage(
                        conversation.thread_id,
                        "VIEWING_CANCELLED"
                    )

                    db.commit()

                    print(
                        f"Cancelled viewing "
                        f"{conversation.thread_id}"
                    )

                except Exception as e:

                    print(
                        f"Cancellation failed: {e}"
                    )