import re
import time
from dataclasses import dataclass

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.ai.prompts import (
    build_cancel_viewing_prompt,
    build_drive_distance,
    build_initial_enquiry_prompt,
    build_reply_prompt,
    names_generator,
)
from app.ai.conversation_memory import (
    latest_landlord_asked_for_phone,
    outbound_count,
    phone_shared_state,
    viewing_requested,
)
from app.ai.personas import generate_phone_share_reply
from app.ai.validators import is_valid_reply, remove_unapproved_phone_numbers
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


@dataclass
class ReplyGenerationResult:
    reply: str | None
    prompt: str | None
    completion: str | None
    model: str
    temperature: float
    is_valid: bool
    error: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


def _default_completion_create(**kwargs):
    return client.chat.completions.create(**kwargs)


def format_conversation(messages):
    lines = []
    for msg in messages:
        lines.append(f"{msg['sender'].upper()}: {msg['message']}")
    return "\n".join(lines)


def _format_simulation_conversation(messages) -> str:
    lines = []
    for message in messages:
        speaker = getattr(message, "speaker", None)
        content = getattr(message, "message", None)
        if speaker is None and isinstance(message, dict):
            speaker = message.get("speaker") or message.get("sender")
            content = message.get("message")
        if not speaker or content is None:
            continue
        lines.append(f"{str(speaker).upper()}: {content}")
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
    conversation=None,
    landlord_attitude=None,
    conversation_style=None,
    retries=3,
    base_delay=2,
):
    conversation_state = conversation
    conversation = format_conversation(messages)
    landlord_asked_number = latest_landlord_asked_for_phone(messages)
    number_shared = phone_shared_state(messages, persona, conversation=conversation_state)
    sent_count = outbound_count(messages)

    if landlord_asked_number and not number_shared:
        phone_reply = generate_phone_share_reply(
            persona,
            landlord_attitude=landlord_attitude or "responsive",
        )
        if phone_reply:
            return (
                remove_unapproved_phone_numbers(
                    phone_reply,
                    (persona or {}).get("mobile_number"),
                ),
                None,
            )

    def build_prompt(conversation_text: str) -> str:
        place = None
        if stage == "VIEWING_BOOKED":
            place = generate_distant_location(property_location or "")
        return build_reply_prompt(
            conversation_text,
            stage or "VIEWING_DISCUSSION",
            persona=persona,
            place=place,
            landlord_attitude=landlord_attitude,
            conversation_style=conversation_style,
            viewing_requested=viewing_requested(messages),
            phone_number_shared=number_shared,
            landlord_asked_for_number=landlord_asked_number,
            outbound_count=sent_count,
        )

    result = generate_reply_result(
        conversation,
        model=settings.OPENAI_REPLY_MODEL,
        temperature=0.7,
        prompt_builder=build_prompt,
        retries=retries,
        base_delay=base_delay,
    )
    if not result.is_valid:
        return None, result.error or "invalid_ai_reply"
    reply = remove_unapproved_phone_numbers(
        result.reply,
        (persona or {}).get("mobile_number"),
    )
    if not is_valid_reply(reply):
        return None, "invalid_ai_reply"
    return reply, None


def generate_reply_result(
    prompt_messages,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    prompt_builder=None,
    retries: int = 3,
    base_delay: int = 2,
):
    conversation = prompt_messages
    if not isinstance(prompt_messages, str):
        conversation = _format_simulation_conversation(prompt_messages)

    if prompt_builder is None:
        prompt = build_reply_prompt(conversation)
    else:
        prompt = prompt_builder(conversation)

    selected_model = model or settings.OPENAI_REPLY_MODEL
    last_error = None

    for attempt in range(1, retries + 1):
        started_at = time.perf_counter()
        try:
            response = _default_completion_create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            completion = (response.choices[0].message.content or "").strip()
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0

            if not is_valid_reply(completion):
                logger.warning("Invalid AI reply generated")
                return ReplyGenerationResult(
                    reply=None,
                    prompt=prompt,
                    completion=completion,
                    model=selected_model,
                    temperature=temperature,
                    is_valid=False,
                    error="invalid_ai_reply",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                )

            return ReplyGenerationResult(
                reply=completion,
                prompt=prompt,
                completion=completion,
                model=selected_model,
                temperature=temperature,
                is_valid=True,
                error=None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            )

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

    return ReplyGenerationResult(
        reply=None,
        prompt=prompt,
        completion=None,
        model=selected_model,
        temperature=temperature,
        is_valid=False,
        error=last_error or "ai_reply_failed",
    )


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
            reply = remove_unapproved_phone_numbers(
                reply,
                (persona or {}).get("mobile_number"),
            )

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
