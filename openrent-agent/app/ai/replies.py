import json
import re
import time
from dataclasses import dataclass

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.ai.prompts import (
    build_cancel_viewing_prompt,
    build_drive_distance,
    build_follow_up_prompt,
    build_initial_enquiry_prompt,
    build_pre_cancel_number_ask_prompt,
    build_reply_prompt,
    build_viewing_detection_prompt,
    names_generator,
    LANDLORD_NUMBER_CAPTURE_DESIGNS,
)
from app.ai.conversation_memory import (
    detect_screening_questions,
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

# Ordered longest-first so alternation can't be shadowed by a shorter prefix.
_UK_CITY_NAMES = sorted([
    "Aberdeen", "Ayr", "Barnsley", "Basingstoke", "Bath", "Birmingham",
    "Blackpool", "Bolton", "Bournemouth", "Bradford", "Brighton", "Bristol",
    "Burnley", "Cambridge", "Canterbury", "Cardiff", "Carlisle", "Chester",
    "Cheltenham", "Coventry", "Crawley", "Crewe", "Derby", "Doncaster",
    "Dundee", "Durham", "Eastbourne", "Edinburgh", "Exeter", "Glasgow",
    "Gloucester", "Guildford", "Halifax", "Hereford", "Huddersfield", "Hull",
    "Inverness", "Ipswich", "Kilmarnock", "Lancaster", "Leeds", "Leicester",
    "Liverpool", "London", "Luton", "Manchester", "Middlesbrough",
    "Newcastle", "Newport", "Northampton", "Norwich", "Nottingham", "Oxford",
    "Paisley", "Perth", "Peterborough", "Plymouth", "Portsmouth", "Preston",
    "Reading", "Rotherham", "Salford", "Salisbury", "Sheffield", "Shrewsbury",
    "Southampton", "Stafford", "Stirling", "Stockport", "Stoke", "Sunderland",
    "Swansea", "Swindon", "Taunton", "Torquay", "Truro", "Wakefield",
    "Warrington", "Winchester", "Wolverhampton", "Wrexham", "York",
], key=len, reverse=True)

_UK_CITY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in _UK_CITY_NAMES) + r')\b',
    re.IGNORECASE,
)


def _detect_city_mismatch(reply: str, stored_city: str) -> str | None:
    """Return the first known UK city in `reply` that differs from `stored_city`, else None."""
    stored_lower = stored_city.lower()
    for m in _UK_CITY_RE.finditer(reply):
        if m.group(0).lower() != stored_lower:
            return m.group(0)
    return None


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


def _sanitize_dashes(text: str) -> str:
    """
    Replace em and en dashes with commas so generated messages
    feel natural rather than AI-polished.
    """
    text = text.replace("—", ",")  # em dash —
    text = text.replace("–", ",")  # en dash –
    return text


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
    conversation_design_id=None,
    landlord_attitude=None,
    conversation_style=None,
    travel_city=None,
    thread_id=None,
    retries=3,
    base_delay=2,
):
    conversation_state = conversation
    conversation = format_conversation(messages)
    landlord_asked_number = latest_landlord_asked_for_phone(messages)
    number_shared = phone_shared_state(messages, persona, conversation=conversation_state)
    sent_count = outbound_count(messages)

    _number_ask_keywords = (
        "your number", "phone number", "mobile number", "your mobile",
        "your contact", "contact number", "get your number", "share your number",
        "could i get your number", "can i get your number",
    )
    num_ask_count = sum(
        1 for m in (messages or [])
        if str(m.get("direction") or m.get("sender") or "").lower() in {"outbound", "operator", "ai", "user"}
        and any(kw in (m.get("message") or m.get("content") or m.get("text") or "").lower() for kw in _number_ask_keywords)
    )

    # Detect landlord screening questions in the latest message.
    # When present the AI must answer them first — skip the phone-reply shortcut
    # so the full prompt (which instructs "answer questions first") takes over.
    screening_questions = detect_screening_questions(messages)
    if screening_questions:
        tid_tag = f" thread_id={thread_id}" if thread_id else ""
        logger.info(
            f"LANDLORD_QUESTION_DETECTED{tid_tag}"
            f" QUESTION_COUNT={len(screening_questions)}"
            f" topics={screening_questions}"
        )

    if (
        landlord_asked_number
        and not number_shared
        and not screening_questions  # defer to full prompt when screening present
        and conversation_design_id not in LANDLORD_NUMBER_CAPTURE_DESIGNS
    ):
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
        # travel_city is pre-resolved for all stages by the caller; use it
        # directly so the origin city stays consistent across every reply.
        place = travel_city
        return build_reply_prompt(
            conversation_text,
            stage or "VIEWING_DISCUSSION",
            persona=persona,
            place=place,
            landlord_attitude=landlord_attitude,
            conversation_style=conversation_style,
            conversation_design_id=conversation_design_id,
            viewing_requested=viewing_requested(messages),
            phone_number_shared=number_shared,
            landlord_asked_for_number=landlord_asked_number,
            outbound_count=sent_count,
            phone_ask_count=num_ask_count,
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

    # Travel city consistency guard: if the AI slipped in a different city,
    # regenerate up to twice before accepting whatever we have.
    if travel_city and stage == "VIEWING_BOOKED":
        for _attempt in range(2):
            conflicting = _detect_city_mismatch(reply, travel_city)
            if not conflicting:
                break
            tid_tag = f" thread_id={thread_id}" if thread_id else ""
            logger.warning(
                f"TRAVEL_CITY_MISMATCH{tid_tag}"
                f" stored_city={travel_city} generated_city={conflicting}"
            )
            regen = generate_reply_result(
                conversation,
                model=settings.OPENAI_REPLY_MODEL,
                temperature=0.7,
                prompt_builder=build_prompt,
            )
            if regen.is_valid:
                candidate = remove_unapproved_phone_numbers(
                    regen.reply, (persona or {}).get("mobile_number")
                )
                if is_valid_reply(candidate):
                    reply = candidate

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
            completion = _sanitize_dashes((response.choices[0].message.content or "").strip())
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


_CANCEL_PHONE_ACK_RE = re.compile(
    r"thanks for (sharing|sending|your)\s+(your\s+)?(number|phone|mobile|contact|details)"
    r"|got your number|received your number|saved your number"
    r"|thanks for (the|that) number",
    re.I,
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
            reply = _sanitize_dashes(response.choices[0].message.content.strip())
            if not is_valid_reply(reply):
                return None, "invalid_cancellation_reply"
            if _CANCEL_PHONE_ACK_RE.search(reply):
                logger.warning(
                    f"CANCEL_PHONE_ACK_BLOCKED attempt={attempt} reply_preview={reply[:80]!r}"
                )
                last_error = "cancel_reply_phone_ack"
                continue
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


def generate_follow_up_message(messages=None, follow_up_number=1, retries=3, base_delay=2):
    """Generate a check-in nudge for a cold lead (landlord never replied)."""
    conversation = format_conversation(messages or [])
    prompt = build_follow_up_prompt(conversation, follow_up_number)

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            reply = _sanitize_dashes(response.choices[0].message.content.strip())
            if not is_valid_reply(reply):
                last_error = "invalid_follow_up_reply"
                continue
            return reply, None
        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"Follow-up message attempt {attempt}/{retries} failed: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected follow-up message error: {exc}")
            break

    return None, last_error or "follow_up_reply_failed"


def generate_handoff_message(messages=None, retries=3, base_delay=2):
    conversation = format_conversation(messages or [])
    prompt = f"""
You are writing one final OpenRent reply after a landlord has shared their contact details.

Write a short, natural acknowledgement.

Guidelines:
- Friendly and human
- One sentence only
- No mention of AI
- No mention of automation
- No mention of phone extraction
- No mention of handoff
- No mention of internal workflow
- Do not ask a question

Examples:
Perfect, thanks for sharing your number. I'll be in touch.
Thanks for sending that over. I'll save your details and look forward to speaking soon.
Brilliant, thanks for sharing your contact details. Looking forward to arranging everything.

Conversation:
{conversation}

Return only the message text.
""".strip()

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            reply = _sanitize_dashes(response.choices[0].message.content.strip())
            if not is_valid_reply(reply):
                return None, "invalid_handoff_reply"
            return reply, None
        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(
                f"Handoff message attempt {attempt}/{retries} failed: {exc}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected handoff message error: {exc}")
            break

    return None, last_error or "handoff_reply_failed"


def generate_cancel_viewing_message(messages, retries=3, base_delay=2):
    """Generate a polite viewing cancellation message and return (reply, error)."""
    from app.ai.prompts import build_cancel_viewing_prompt
    conversation = format_conversation(messages or [])
    result = generate_reply_result(
        conversation,
        model=settings.OPENAI_REPLY_MODEL,
        temperature=0.7,
        prompt_builder=lambda _: build_cancel_viewing_prompt(conversation),
        retries=retries,
        base_delay=base_delay,
    )
    if result.is_valid:
        return result.reply, None
    return None, result.error or "cancel_reply_failed"


def ai_detect_viewing_arranged(messages, retries=2, base_delay=1):
    """
    Use AI to determine if a viewing is genuinely arranged in this conversation.
    Returns dict with keys: viewing_arranged (bool), viewing_datetime (str|None), reason (str).
    Called only when the banner scan found nothing, as a fallback.
    """
    conversation = format_conversation(messages or [])
    prompt = build_viewing_detection_prompt(conversation)

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            # Strip markdown code fences if the model wraps the JSON
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S).strip()
            result = json.loads(raw)
            return {
                "viewing_arranged": bool(result.get("viewing_arranged", False)),
                "viewing_datetime": result.get("viewing_datetime") or None,
                "reason": result.get("reason", ""),
            }
        except (RateLimitError, APITimeoutError, APIError) as exc:
            logger.warning(f"AI viewing detection attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(base_delay)
        except Exception as exc:
            logger.warning(f"AI viewing detection attempt {attempt}/{retries} error: {exc}")
            if attempt < retries:
                time.sleep(base_delay)

    return {"viewing_arranged": False, "viewing_datetime": None, "reason": "detection_failed"}


def detect_short_term_tenancy(messages, retries=2, base_delay=1) -> bool:
    """
    Return True if the landlord has explicitly stated the property is only
    available short-term (less than 12 months).  Defaults to False on any
    error so we never incorrectly close a conversation.
    """
    recent = messages[-6:] if len(messages) > 6 else messages
    conversation = format_conversation(recent)
    prompt = f"""You are analysing a UK rental conversation to determine if the landlord has explicitly stated this property is only available for a short-term tenancy (less than 12 months).

Return JSON only: {{"is_short_term": true/false, "reason": "brief explanation"}}

Rules:
- Only return true if the landlord EXPLICITLY STATED the property is short-term, temporary, holiday let, or has a maximum tenancy of less than 12 months.
- Phrases like "short-term let", "maximum 6 months", "only available until [date]", "minimum 2 months maximum 4 months" mean is_short_term = true.
- If the tenant mentioned "long-term" but the landlord said nothing about tenancy length, return false.
- If unsure, return false.

Conversation:
{conversation}

JSON only:""".strip()

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S).strip()
            result = json.loads(raw)
            is_short = bool(result.get("is_short_term", False))
            logger.info(
                f"SHORT_TERM_DETECTION is_short={is_short} "
                f"reason={result.get('reason', '')!r}"
            )
            return is_short
        except Exception as exc:
            logger.warning(f"Short-term detection attempt {attempt}/{retries} error: {exc}")
            if attempt < retries:
                time.sleep(base_delay)

    return False


def generate_short_term_close_message(messages=None, retries=3, base_delay=2):
    """Generate a polite closing message for short-term/holiday let properties."""
    conversation = format_conversation(messages or [])
    prompt = f"""You are writing a short, polite reply to a landlord who has indicated their property is only available as a short-term let (less than 12 months).

Write a brief, friendly message explaining you are looking for a long-term rental (minimum 12 months) and wishing them well.

Guidelines:
- One or two sentences maximum
- Friendly and warm tone
- No mention of AI or automation
- Do not ask any questions

Examples:
Thanks so much for getting back to me — unfortunately we're specifically looking for a long-term let of at least 12 months, so this one won't quite work for us. All the best with finding a tenant!
Thank you for letting me know — we're ideally looking for somewhere for at least 12 months, so this property won't be the right fit for us. Wishing you all the best!

Conversation:
{conversation}

Return only the message text.""".strip()

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            reply = _sanitize_dashes(response.choices[0].message.content.strip())
            if not is_valid_reply(reply):
                return None, "invalid_short_term_close"
            return reply, None
        except (RateLimitError, APITimeoutError, APIError) as exc:
            last_error = str(exc)
            logger.warning(f"Short-term close attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(base_delay * attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.exception(f"Unexpected short-term close error: {exc}")
            break

    return None, last_error or "short_term_close_failed"


def generate_pre_cancel_number_ask(messages, place=None, retries=3, base_delay=2):
    """Generate a natural phone-ask message to send one run before cancelling a viewing."""
    conversation = format_conversation(messages or [])
    result = generate_reply_result(
        conversation,
        model=settings.OPENAI_REPLY_MODEL,
        temperature=0.7,
        prompt_builder=lambda _: build_pre_cancel_number_ask_prompt(conversation, place=place),
        retries=retries,
        base_delay=base_delay,
    )
    if result.is_valid:
        return result.reply, None
    return None, result.error or "pre_cancel_number_ask_failed"


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

            reply = _sanitize_dashes(response.choices[0].message.content.strip())
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
