"""
Business hours, reply scheduling, LLM-generated closings, and WhatsApp Web send.
"""
from __future__ import annotations

import random
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


def build_name_ask(history: Optional[list[dict]] = None) -> str:
    """Ask who we're speaking with, phrased naturally from the conversation so far."""
    try:
        prompt = (
            "Someone has messaged this WhatsApp number about a property enquiry from OpenRent, "
            "but we don't know their name yet. "
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
    try:
        prompt = (
            "Someone has messaged this WhatsApp number about a property enquiry from OpenRent. "
            "We know who they are but not which property they mean. "
            "Persona fact: my wife handles our OpenRent enquiries, which is why we're texting from "
            "this number. "
            "Write a very short, casual WhatsApp message asking which property or address they mean, "
            "working the wife/OpenRent detail in naturally. "
            "Rules: one or two sentences, no em dashes or en dashes, no bullet points, "
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
        "Hi, my wife manages our enquiries on OpenRent. "
        "Could you let us know the property address or details so we can look it up?"
    )


def send_whatsapp_message(phone: str, message: str) -> bool:
    """Send via the Playwright browser worker (replaces Baileys HTTP call)."""
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
