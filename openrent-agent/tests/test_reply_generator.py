from app.ai.validators import remove_unapproved_phone_numbers


def test_remove_unapproved_phone_numbers_without_assigned_mobile():
    unapproved = "".join(str(digit) for digit in range(10))

    reply = remove_unapproved_phone_numbers(f"You can reach me on {unapproved}.")

    assert unapproved not in reply
    assert reply == "You can reach me on."


def test_remove_unapproved_phone_numbers_keeps_assigned_mobile_in_any_format():
    # The approved number is matched on normalized digits, so it survives
    # however the model formats it ("+447900111222" or "+44 790 011 122 2").
    # See remove_unapproved_phone_numbers: keep "comparing on digits so the model
    # may write it however it likes ... and it still survives."
    assigned = "+" + "".join(("44", "7900", "111", "222"))
    same_digits_different_format = " ".join(assigned[index:index + 3] for index in range(0, len(assigned), 3))

    exact_reply = remove_unapproved_phone_numbers(
        f"My number is {assigned}.",
        assigned,
    )
    formatted_reply = remove_unapproved_phone_numbers(
        f"My number is {same_digits_different_format}.",
        assigned,
    )
    unapproved_reply = remove_unapproved_phone_numbers(
        "Call the office on 020 7946 0000.",
        assigned,
    )

    assert assigned in exact_reply
    # Same digits, different formatting = still the approved number -> kept.
    assert same_digits_different_format in formatted_reply
    # A genuinely different (unapproved) number is still stripped.
    assert "020 7946 0000" not in unapproved_reply
