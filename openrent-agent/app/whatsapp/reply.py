"""Business hours, reply scheduling, LLM-generated closings, and WhatsApp send."""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Optional

from zoneinfo import ZoneInfo

from openai import OpenAI

from app.config import settings
from app.utils.logger import logger

UK_TZ = ZoneInfo("Europe/London")

_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=15.0)


def is_business_hours() -> bool:
    """Return True if current UK time is between 08:00 and 23:00."""
    now = datetime.now(UK_TZ)
    return 8 <= now.hour < 23


def next_reply_time() -> datetime:
    """
    In business hours: now + random(60, 180) seconds.
    Out of hours: next 08:00 UK + random(30, 300) seconds.
    """
    now_uk = datetime.now(UK_TZ)

    if is_business_hours():
        delay = random.randint(60, 180)
        scheduled = datetime.utcnow() + timedelta(seconds=delay)
        return scheduled

    # Calculate next 08:00 UK
    next_08 = now_uk.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_uk.hour >= 23:
        next_08 += timedelta(days=1)

    # Convert to UTC
    next_08_utc = next_08.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    extra = random.randint(30, 300)
    return next_08_utc + timedelta(seconds=extra)


def generate_closing_reply(name: Optional[str] = None) -> str:
    """Generate a closing reply after a landlord has been matched to a property."""
    try:
        prompt = (
            "A landlord has texted a WhatsApp number about a property enquiry on OpenRent. "
            "We've now identified which property they're advertising. "
            "Write a very short, warm closing message (1 sentence) saying thanks and that we'll "
            "discuss and get back to them. "
            "Rules: casual WhatsApp tone, no names, no personal details, no em dashes, "
            "no bullet points, vary the phrasing each time, sound like a real person not a template. "
            "Reply with ONLY the message text, no quotes."
        )
        response = _client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=60,
        )
        text = response.choices[0].message.content.strip().strip('"')
        if text:
            return text
    except Exception as exc:
        logger.warning(f"WHATSAPP_CLOSING_LLM_FAILED error={exc}")

    return "Thanks for getting in touch! We'll have a discuss and get back to you soon."


def _format_history(history: Optional[list[dict]]) -> str:
    if not history:
        return "(no prior messages)"
    lines = []
    for item in history:
        if not isinstance(item, dict):
            continue
        text = item.get("message")
        if not text:
            continue
        sender = "US" if item.get("direction") == "outbound" else "LANDLORD"
        lines.append(f"{sender}: {text}")
    return "\n".join(lines) if lines else "(no prior messages)"


# Who is who on this WhatsApp line. Without this the model guessed the texter
# was a prospective tenant ("which property you're interested in") when it is a
# LANDLORD whose listing we (the tenants) enquired about (2026-09-30).
_ROLE_CONTEXT = (
    "You are texting on WhatsApp as a tenant, one half of a couple looking for a place to rent. "
    "We sent enquiries on OpenRent about properties that landlords are advertising, and gave "
    "some of those landlords this WhatsApp number. The person messaging you is one of those "
    "landlords (or someone acting for them) getting back to us about THEIR property. "
    "Your partner sent the OpenRent enquiries and told the landlord this is your WhatsApp, "
    "because you are the one sorting out the viewings. "
    "Refer to the person who made the enquiries only as \"my partner\". Never give your own "
    "name or any name they didn't use first (using the landlord's own name back is fine). "
)

# A landlord who was told "my partner's WhatsApp" often opens by asking for the
# person they chatted with on OpenRent ("is this Nicola?", "Hi Sarah, ..."). The
# model reliably fumbled that ("I'm my partner's partner"), so the name is
# detected here and the exact self-introduction is supplied to it.
_ASKED_FOR_NAME_RES = [
    re.compile(r"\b(?i:is this|is that|are you|am i (?:speaking|talking|chatting) (?:to|with))\s+([A-Z][a-z]{1,20})\b"),
    re.compile(r"^\s*(?i:hi|hello|hey|hiya|dear|morning|afternoon|evening)[,!\s]+([A-Z][a-z]{1,20})\b"),
]
_NOT_A_NAME = {
    "There", "All", "Mate", "Sir", "Madam", "Guys", "Everyone", "Again", "Yes", "Yeah",
    "Hi", "Hello", "Hey", "The", "This", "That", "Openrent", "Whatsapp", "Ok", "Okay",
    "Still", "Available", "Interested", "Good", "Thanks", "Thank", "It", "My", "Your",
}


def _name_asked_for(history: Optional[list[dict]]) -> Optional[str]:
    """Name the landlord used for us in their LATEST message, if any."""
    latest = next(
        (item.get("message") for item in reversed(history or [])
         if isinstance(item, dict) and item.get("direction") != "outbound" and item.get("message")),
        None,
    )
    if not latest:
        return None
    for pattern in _ASKED_FOR_NAME_RES:
        match = pattern.search(latest)
        if match and match.group(1) not in _NOT_A_NAME:
            return match.group(1)
    return None


def build_name_ask(history: Optional[list[dict]] = None) -> str:
    """Ask who we're speaking with, phrased naturally from the conversation so far."""
    try:
        prompt = (
            _ROLE_CONTEXT
            + "We don't know their name yet. "
            "Write a very short, casual WhatsApp message asking who you're speaking with. "
            "Rules: one sentence, no names, no em dashes or en dashes, no bullet points, "
            "no brackets or placeholders, vary the phrasing each time, sound like a real person "
            "texting, not a template. Reply with ONLY the message text, no quotes.\n\n"
            f"Conversation so far:\n{_format_history(history)}"
        )
        response = _client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=60,
        )
        text = response.choices[0].message.content.strip().strip('"')
        if text:
            return text
    except Exception as exc:
        logger.warning(f"WHATSAPP_NAME_ASK_LLM_FAILED error={exc}")

    return "Hi! Sorry, could I ask who I'm speaking with?"


def build_property_ask(name: Optional[str] = None, history: Optional[list[dict]] = None) -> str:
    """Ask which property they mean, phrased naturally from the conversation so far."""
    asked_name = _name_asked_for(history)
    try:
        prompt = (
            _ROLE_CONTEXT
            + "We don't yet know which of their properties they're getting in touch about, and "
            "we enquired about several, so we need to match them to the right enquiry. "
            "Persona fact: my partner handles our OpenRent messages. "
            "Write a very short, casual WhatsApp reply that asks which of their properties (the "
            "address or area) they're messaging about, and briefly says my partner is the one who "
            "handles our OpenRent messages so we can check the enquiry. Always refer to them as "
            "\"my partner\". If their message is just a greeting or a check-in, answer that briefly "
            "first, then ask. If they ask who you are (or how they came to be talking to you), "
            "answer that first, relaxed and in the first person, along the lines of: my partner "
            "messaged you on OpenRent about your place and gave you this number, I'm sorting out "
            "the viewings. "
            + (
                f"They asked for {asked_name}, who is your partner, so start your reply with "
                f"\"Hi, it's {asked_name}'s partner here\" and then ask. "
                if asked_name else ""
            )
            + "Rules: one or two sentences, no em dashes or en dashes, no bullet points, "
            "no brackets or placeholders, vary the phrasing each time, sound like a real person "
            "texting, not a template. Reply with ONLY the message text, no quotes.\n\n"
            f"Conversation so far:\n{_format_history(history)}"
        )
        response = _client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=60,
        )
        text = response.choices[0].message.content.strip().strip('"')
        if text:
            return text
    except Exception as exc:
        logger.warning(f"WHATSAPP_PROPERTY_ASK_LLM_FAILED error={exc}")

    return (
        "Hi, my partner manages our enquiries on OpenRent. "
        "Could you let us know the property address or details so we can look it up?"
    )


def send_whatsapp_message(phone: str, message: str) -> bool:
    """Send via the active WhatsApp transport worker."""
    import asyncio
    from app.whatsapp.browser_worker import get_worker
    worker = get_worker()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                worker.send_message(phone, message), loop
            )
            return future.result(timeout=60)
        return asyncio.run(worker.send_message(phone, message))
    except Exception as exc:
        logger.warning(f"WHATSAPP_SEND_FAILED phone={phone} error={exc}")
        return False
