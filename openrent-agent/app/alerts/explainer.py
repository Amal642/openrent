"""
AI Explainer: turns a raw AlertEvent into a short plain-English diagnosis.
Optional by design — if the LLM call fails for any reason, callers just send
the alert without it. Same OpenAI client pattern as app.whatsapp.reply.
"""
from __future__ import annotations

from openai import OpenAI

from app.config import settings
from app.utils.logger import logger

_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=15.0)


def explain(*, source: str, title: str, detail: str, context: str | None) -> str | None:
    try:
        prompt = (
            "An automated rental-listing system hit a failure. Given the raw "
            "details below, write a 3-line plain-English diagnosis for the "
            "on-call person monitoring it over Telegram:\n"
            "Line 1: what broke, in one short sentence.\n"
            "Line 2: most likely cause.\n"
            "Line 3: a concrete next action to take.\n"
            "No preamble, no markdown headers, just the 3 lines.\n\n"
            f"Source: {source}\n"
            f"Title: {title}\n"
            f"Detail: {detail[:1500]}\n"
            f"Context: {context or '(none)'}"
        )
        response = _client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
        text = response.choices[0].message.content.strip()
        return text or None
    except Exception as exc:
        logger.warning(f"ALERT_EXPLAINER_FAILED source={source} title={title!r} error={exc}")
        return None
