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
