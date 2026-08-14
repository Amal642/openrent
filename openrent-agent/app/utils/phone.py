import re


def normalize_uk_phone(phone):

    if not phone:
        return None

    # Remove spaces/symbols
    phone = re.sub(
        r"[^\d+]",
        "",
        phone
    )

    # 00 international access code → leading +
    if phone.startswith("00") and not phone.startswith("0044"):
        phone = "+" + phone[2:]

    # Foreign number (a landlord may be based abroad): keep the international
    # E.164 form as-is when it carries a non-UK country code and a plausible
    # length. We save numbers from any country, not just the UK.
    if phone.startswith("+") and not phone.startswith("+44"):
        return phone if re.fullmatch(r"\+\d{7,15}", phone) else None

    # Convert +44 → 0
    if phone.startswith("+44"):

        phone = (
            "0" + phone[3:]
        )

    # Convert 44 → 0
    elif phone.startswith("44"):

        phone = (
            "0" + phone[2:]
        )

    # UK number (0-prefixed): must be exactly 11 digits. Reject wrong-length
    # values (typos, truncations, or digits stitched from unrelated messages) —
    # a malformed UK number is not a usable lead.
    if phone.startswith("0"):
        return phone if re.fullmatch(r"0\d{10}", phone) else None

    # Bare number, no "+" and not UK-shaped: treat as a foreign number that
    # arrived without its country prefix, and keep it if it is a plausible
    # phone-number length. Save numbers from any country, not just the UK.
    if re.fullmatch(r"\d{7,15}", phone):
        return phone

    return None