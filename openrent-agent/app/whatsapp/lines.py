"""
Our WhatsApp numbers ("lines") and how a contact maps to one.

A contact remembers the phone_number_id it last wrote to; replies go out from
that line. With a single configured number every helper here collapses to the
pre-multi-number behaviour.
"""
from __future__ import annotations

import re
from typing import Optional

from app.config import settings


def national_digits(number: Optional[str]) -> str:
    """UK-normalised digits: "07783 129181", "+44 7783 129181", "447783129181"
    all become "7783129181" so a persona mobile and Meta's display number compare."""
    digits = re.sub(r"\D", "", number or "")
    if digits.startswith("44"):
        digits = digits[2:]
    return digits.lstrip("0")


def thread_giveout_number(messages, account_number: Optional[str], live_numbers) -> Optional[str]:
    """The give-out number to use on one OpenRent thread.

    A landlord who was already given one of our live numbers must keep seeing
    that number: moving an account to another line would otherwise offer a
    second, different "partner's WhatsApp" mid-thread, which reads as fake, and
    break the "already shared" checks. So: the live number we most recently gave
    in this thread, else the account's current number.
    """
    from app.ai.personas import TENANT_SENDERS, tenant_shared_phone

    live = [n for n in (live_numbers or ()) if n]
    if not live:
        return account_number
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender not in TENANT_SENDERS:
            continue
        for number in live:
            if tenant_shared_phone([message], number):
                return number
    return account_number


def pin_thread_giveout_number(persona: Optional[dict], messages, live_numbers) -> Optional[dict]:
    """Persona copy whose mobile_number is this thread's give-out number."""
    if not persona or not persona.get("mobile_number"):
        return persona
    number = thread_giveout_number(messages, persona["mobile_number"], live_numbers)
    if national_digits(number) == national_digits(persona["mobile_number"]):
        return persona
    return {**persona, "mobile_number": number}


def default_phone_number_id() -> str:
    return settings.META_WA_PHONE_NUMBER_ID


def accepted_phone_number_ids() -> set[str]:
    ids = {settings.META_WA_PHONE_NUMBER_ID}
    ids.update(part.strip() for part in settings.META_WA_PHONE_NUMBER_IDS.split(","))
    return {i for i in ids if i}


def meta_send_phone_number_id(line_phone_number_id: Optional[str]) -> str:
    """The line to send from: the contact's own line when it's one of ours,
    otherwise the default (unknown/retired lines never get a send attempt)."""
    if line_phone_number_id and str(line_phone_number_id) in accepted_phone_number_ids():
        return str(line_phone_number_id)
    return default_phone_number_id()
