import re
import time

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.config import settings
from app.ai.prompts import (
    build_phone_extraction_prompt
)
from app.utils.logger import logger


client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=25.0
)


def regex_extract_phone(messages):
    """Return the most-recent valid UK phone number found in `messages`.

    Processes messages individually in order so a landlord correction (later
    message) overwrites an earlier, incorrect number.  Concatenating all
    messages before searching caused the regex to fuse adjacent numbers and
    always return the first occurrence.
    """
    patterns = [
        r"(\+44\d{10,12})",
        r"(07\d{9})",
        r"(447\d{9})",
    ]
    last_found = None
    for msg in messages:
        cleaned = re.sub(r"[^\d+]", "", msg)
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if match:
                last_found = match.group(1)
                break  # one phone per message; move to the next message
    return last_found


def ai_extract_phone(messages, retries=3, base_delay=2):

    text = "\n".join(messages)

    prompt = build_phone_extraction_prompt(
        text
    )

    for attempt in range(1, retries + 1):

        try:

            response = client.chat.completions.create(
                model="gpt-4.1-mini",

                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],

                temperature=0
            )

            result = (
                response.choices[0]
                .message.content
                .strip()
            )

            if result.upper() == "NONE":
                return None

            return result

        except (RateLimitError, APITimeoutError, APIError) as e:
            logger.warning(
                f"OpenAI phone extraction attempt {attempt}/{retries} failed: {e}"
            )

            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as e:
            logger.exception(f"Unexpected AI phone extraction error: {e}")
            break

    return None
