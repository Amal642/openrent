from openai import OpenAI
from openai import (
    RateLimitError,
    APIError,
    APITimeoutError
)

from app.config import settings
from app.ai.prompts import (
    build_reply_prompt
)
from app.ai.validators import (
    is_valid_reply
)

client = OpenAI(
    api_key=settings.OPENAI_API_KEY
)


def format_conversation(messages):

    lines = []

    for msg in messages:

        sender = msg["sender"]

        text = msg["message"]

        lines.append(
            f"{sender.upper()}: {text}"
        )

    return "\n".join(lines)


def generate_reply(messages):

    try:

        conversation = format_conversation(
            messages
        )

        prompt = build_reply_prompt(
            conversation
        )

        response = client.chat.completions.create(

            model="gpt-4.1-mini",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.7
        )

        reply = (
            response.choices[0]
            .message.content
            .strip()
        )

        if not is_valid_reply(reply):

            print(
                "Invalid AI reply detected"
            )

            return None

        return reply

    except RateLimitError:

        print(
            "OpenAI rate limit hit"
        )

        return None

    except APITimeoutError:

        print(
            "OpenAI timeout"
        )

        return None

    except APIError as e:

        print(
            f"OpenAI API error: {e}"
        )

        return None

    except Exception as e:

        print(
            f"AI reply generation failed: {e}"
        )

        return None