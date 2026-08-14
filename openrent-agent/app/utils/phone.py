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
    # landlines). Reject anything else — too short, over-long, or garbage stitched
    # from unrelated digits — so a malformed extraction is never saved as a lead.
    if not re.fullmatch(r"0\d{10}", phone):
        return None

    return phone