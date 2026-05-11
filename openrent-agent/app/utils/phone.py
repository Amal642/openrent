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

    return phone