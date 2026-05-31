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

    combined = "\n".join(messages)
    cleaned = re.sub(r"[^\d+]", "", combined)

    patterns = [

        r"(\+44\d{10,12})",

        r"(07\d{9})",

        r"(447\d{9})"
    ]

    for pattern in patterns:

        match = re.search(pattern, cleaned)

        if match:
            return match.group(1)

    return None


def ai_extract_phone(messages, retries=3, base_delay=2):

    text = "\n".join(messages)

    prompt = build_phone_extraction_prompt(
        text
    )

    for attempt in range(1, retries + 1):

        try:

            response = client.chat.completions.create(
                model=settings.OPENAI_REPLY_MODEL,

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
