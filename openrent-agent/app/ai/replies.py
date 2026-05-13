import time

from openai import OpenAI
from openai import RateLimitError, APIError, APITimeoutError

from app.config import settings
from app.ai.prompts import build_reply_prompt
from app.ai.validators import is_valid_reply
from app.utils.logger import logger


client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=25.0
)


def format_conversation(messages):
    lines = []
    for msg in messages:
        lines.append(f"{msg['sender'].upper()}: {msg['message']}")
    return "\n".join(lines)


def generate_reply(messages, retries=3, base_delay=2):
    conversation = format_conversation(messages)
    prompt = build_reply_prompt(conversation)

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

            reply = response.choices[0].message.content.strip()

            if not is_valid_reply(reply):
                logger.warning("Invalid AI reply generated")
                return None, "invalid_ai_reply"

            return reply, None

        except (RateLimitError, APITimeoutError, APIError) as e:
            last_error = str(e)
            logger.warning(
                f"OpenAI reply attempt {attempt}/{retries} failed: {e}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as e:
            last_error = str(e)
            logger.exception(f"Unexpected AI reply error: {e}")
            break

    return None, last_error or "ai_reply_failed"