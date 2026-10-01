"""
Direct Meta WhatsApp Cloud API webhook: signature check and payload parsing.

Meta's native shape differs from Kapso's v2 events:
  {"object": "whatsapp_business_account",
   "entry": [{"id": <WABA id>, "changes": [{"field": "messages", "value": {
       "metadata": {"phone_number_id": ..., "display_phone_number": ...},
       "contacts": [{"wa_id": ..., "profile": {"name": ...}}],
       "messages": [...],     # inbound only; may hold several per request
       "statuses": [...]}}]}]}  # delivery receipts for OUR sends, never leads

Signature: X-Hub-Signature-256 = "sha256=" + hex HMAC-SHA256(app secret, raw body).
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.config import settings
from app.utils.logger import logger

# Message types that are not a landlord writing to us: reactions to our own
# messages, number-change notices, and payloads Meta can't render.
_SKIP_TYPES = {"reaction", "system", "unsupported", "errors", "ephemeral"}

_CAPTION_TYPES = ("image", "video", "document")


def signature_is_valid(raw_body: bytes, signature: str | None) -> bool:
    secret = settings.META_APP_SECRET
    if not secret:
        # Fail closed: without the app secret anyone could post fake landlord messages.
        logger.error("WHATSAPP_META_APP_SECRET_NOT_SET rejecting_webhook=True")
        return False
    if not signature:
        return False

    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1].strip()
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied.lower(), expected)


def verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """Return the challenge to echo back if Meta's subscription handshake is valid."""
    expected = settings.META_WEBHOOK_VERIFY_TOKEN
    if not expected or mode != "subscribe" or not token or challenge is None:
        return None
    if not hmac.compare_digest(token, expected):
        return None
    return challenge


def _message_text(item: dict) -> str | None:
    msg_type = item.get("type")
    if msg_type == "text":
        return (item.get("text") or {}).get("body")
    if msg_type == "interactive":
        interactive = item.get("interactive") or {}
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key)
            if isinstance(reply, dict) and reply.get("title"):
                return reply["title"]
        return None
    if msg_type == "button":
        return (item.get("button") or {}).get("text")
    if msg_type in _CAPTION_TYPES:
        return (item.get(msg_type) or {}).get("caption")
    return None


def extract_incoming_messages(payload: dict) -> list[dict]:
    """Flatten a Meta webhook into handler-ready inbound messages.

    Each dict carries the handle_incoming_message kwargs plus
    "phone_number_id" (which of our numbers received it).
    """
    if payload.get("object") != "whatsapp_business_account":
        return []

    extracted: list[dict] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            names = {
                str(c.get("wa_id")): (c.get("profile") or {}).get("name")
                for c in value.get("contacts") or []
                if isinstance(c, dict) and c.get("wa_id")
            }

            for item in value.get("messages") or []:
                if not isinstance(item, dict):
                    continue
                msg_type = item.get("type")
                phone = item.get("from")
                if not phone or msg_type in _SKIP_TYPES:
                    continue

                text = _message_text(item)
                if not text:
                    if not msg_type or msg_type == "text":
                        continue
                    # Voice note / photo / location: the sender's number IS the
                    # lead, so keep it with a placeholder (same as the Kapso path).
                    text = f"[{msg_type} message]"

                timestamp = item.get("timestamp")
                try:
                    timestamp = int(timestamp) if timestamp not in (None, "") else None
                except (TypeError, ValueError):
                    timestamp = None

                extracted.append(
                    {
                        "phone_number": str(phone),
                        "message": str(text),
                        "timestamp": timestamp,
                        "sender_name": names.get(str(phone)),
                        "message_id": item.get("id"),
                        "phone_number_id": phone_number_id,
                    }
                )
    return extracted
