import re
import time

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.ai.prompts import (
    build_cancel_viewing_prompt,
    build_drive_distance,
    build_initial_enquiry_prompt,
    build_reply_prompt,
    names_generator,
)
from app.ai.validators import is_valid_reply
from app.config import settings
from app.utils.logger import logger

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=25.0,
)

FALLBACK_DISTANT_LOCATIONS = [
    "Manchester",
    "Derby",
    "Birmingham",
    "Leicester",
    "Nottingham",
    "Liverpool",
    "Sheffield",
]


def format_conversation(messages):
    lines = []
    for msg in messages:
        lines.append(f"{msg['sender'].upper()}: {msg['message']}")
    return "\n".join(lines)


def generate_names():
    prompt = names_generator()
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        temperature=0.7,
    )
    content = response.choices[0].message.content.strip()
    names = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in ("husband", "wife"):
            names[key] = value.strip()
    return names or {"husband": "James", "wife": "Sophie"}


def _fallback_distant_location(property_location):
    if not property_location:
        return "Manchester"

    index = sum(ord(char) for char in property_location) % len(FALLBACK_DISTANT_LOCATIONS)
    return FALLBACK_DISTANT_LOCATIONS[index]


def _normalize_place_name(raw_value):
    if not raw_value:
        return None

    line = str(raw_value).splitlines()[0].strip()
    line = re.sub(r"^[^A-Za-z]+", "", line)
    line = re.sub(r"[^A-Za-z' -]", "", line)
    line = re.sub(r"\s+", " ", line).strip()

    if not line:
        return None

    words = line.split()
    if len(words) > 3:
        words = words[:3]

    return " ".join(word.capitalize() if word.islower() else word for word in words)


def generate_distant_location(property_location: str, retries=3, base_delay=2) -> str:
    prompt = build_drive_distance(property_location)
    fallback = _fallback_distant_location(property_location)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            place = _normalize_place_name(
                response.choices[0].message.content.strip()
            )
            if place:
                return place
            last_error = "empty_place_response"
        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"Distant location attempt {attempt}/{retries} failed: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected distant location error: {exc}")
            break

    logger.warning(
        f"Using fallback distant location for '{property_location}': {fallback} ({last_error})"
    )
    return fallback


def generate_reply(
    messages,
    stage=None,
    persona=None,
    property_location=None,
    retries=3,
    base_delay=2,
):
    conversation = format_conversation(messages)
    place = None
    if stage == "VIEWING_BOOKED":
        place = generate_distant_location(property_location or "")
    prompt = build_reply_prompt(
        conversation,
        stage,
        persona=persona,
        place=place,
    )

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

        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"OpenAI reply attempt {attempt}/{retries} failed: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected AI reply error: {exc}")
            break

    return None, last_error or "ai_reply_failed"


def generate_cancellation_message(messages=None, retries=3, base_delay=2):
    conversation = format_conversation(messages or [])
    prompt = build_cancel_viewing_prompt(conversation)

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
            )
            reply = response.choices[0].message.content.strip()
            if not is_valid_reply(reply):
                return None, "invalid_cancellation_reply"
            return reply, None
        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"Cancellation message attempt {attempt}/{retries} failed: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected cancellation message error: {exc}")
            break

    return None, last_error or "cancellation_reply_failed"


def generate_initial_property_message(
    metadata,
    persona=None,
    retries=3,
    base_delay=2,
):
    prompt = build_initial_enquiry_prompt(
        metadata,
        persona or {
            "persona_name": "James",
            "persona_partner_name": "Sophie",
            "persona_job": "Software Engineer",
            "persona_partner_job": "Project Coordinator",
            "household_description": "professional couple",
            "message_tone": "brief, casual, realistic",
        },
    )

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=0.8,
            )

            reply = response.choices[0].message.content.strip()

            if len(reply) < 20:
                return None, "short_reply"

            return reply, None

        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"Initial message generation failed {attempt}/{retries}: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(
                f"Unexpected initial message error: {exc}"
            )
            break

    return None, last_error

