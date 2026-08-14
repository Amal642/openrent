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
    # length. Only clearly-malformed values are rejected.
    if phone.startswith("+") and not phone.startswith("+44"):
        return phone if re.fullmatch(r"\+\d{8,15}", phone) else None

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

    # A valid UK number is exactly 11 digits starting 0 (07 mobiles, 01/02/03
    # landlines). Reject wrong-length values (typos, truncations, or digits
    # stitched from unrelated messages) so a malformed capture isn't saved.
    if re.fullmatch(r"0\d{10}", phone):
        return phone

    return None