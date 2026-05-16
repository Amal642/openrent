import time

from openai import OpenAI
from openai import RateLimitError, APIError, APITimeoutError

from app.config import settings
from app.ai.prompts import (build_reply_prompt,build_initial_enquiry_prompt,names_generator)
from app.ai.validators import is_valid_reply
from app.utils.logger import logger
from app.ai.functions import get_random_job

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=25.0
)


def format_conversation(messages):
    lines = []
    for msg in messages:
        lines.append(f"{msg['sender'].upper()}: {msg['message']}")
    return "\n".join(lines)

import random


HOUSEHOLDS = {
    1: [
        {
            "occupants": 1,
            "description": "single working professional"
        }
    ],

    2: [
        {
            "occupants": 2,
            "description": "professional couple"
        }
    ],

    3: [
        {
            "occupants": 3,
            "description": "couple with one child"
        }
    ],

    4: [
        {
            "occupants": 4,
            "description": "family of four"
        }
    ]
}


def generate_household(
    bedrooms
):

    if bedrooms <= 1:
        return random.choice(HOUSEHOLDS[1])

    if bedrooms == 2:
        return random.choice(HOUSEHOLDS[2])

    if bedrooms == 3:
        return random.choice(HOUSEHOLDS[3])

    return random.choice(HOUSEHOLDS[4])

def generate_names():
    prompt = names_generator()
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def generate_reply(messages, stage=None, retries=3, base_delay=2):
    conversation = format_conversation(messages)
    prompt = build_reply_prompt(conversation, stage)

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

def generate_initial_property_message(
    metadata,
    retries=3,
    base_delay=2
):

    household = generate_household(
        metadata.get("bedrooms", 1)
    )
    professions = {
        get_random_job()
    }
    names = generate_names()
    prompt = build_initial_enquiry_prompt(
        metadata,
        household,
        names,
        professions
    )

    last_error = None

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

                temperature=0.8,
            )

            reply = (
                response
                .choices[0]
                .message.content
                .strip()
            )

            if len(reply) < 20:
                return None, "short_reply"

            return reply, None

        except (
            RateLimitError,
            APITimeoutError,
            APIError
        ) as e:

            last_error = str(e)

            logger.warning(
                f"Initial message generation failed "
                f"{attempt}/{retries}: {e}"
            )

            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as e:

            last_error = str(e)

            logger.exception(
                f"Unexpected initial message error: {e}"
            )

            break

    return None, last_error