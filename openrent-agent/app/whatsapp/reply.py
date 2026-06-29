"""
Business hours, reply scheduling, LLM-generated closings, and Baileys HTTP send.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

import httpx
from zoneinfo import ZoneInfo

from openai import OpenAI

from app.config import settings
from app.utils.logger import logger

UK_TZ = ZoneInfo("Europe/London")
BAILEYS_URL = "http://localhost:3001/send"

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


def build_name_ask() -> str:
    return "Hi! Sorry, could I ask who I'm speaking with?"


def build_property_ask(name: Optional[str] = None) -> str:
    return (
        "Hi, my wife manages our enquiries on OpenRent. "
        "Could you let us know the property address or details so we can look it up?"
    )


def send_whatsapp_message(phone: str, message: str) -> bool:
    """POST to Baileys service to send a WhatsApp message."""
    try:
        resp = httpx.post(
            BAILEYS_URL,
            json={"phone": phone, "message": message},
            timeout=10.0,
        )
        resp.raise_for_status()
        logger.info(f"WHATSAPP_SENT phone={phone} status={resp.status_code}")
        return True
    except Exception as exc:
        logger.warning(f"WHATSAPP_SEND_FAILED phone={phone} error={exc}")
        return False
