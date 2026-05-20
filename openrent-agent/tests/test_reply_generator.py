from app.ai.validators import remove_unapproved_phone_numbers


def test_remove_unapproved_phone_numbers_without_assigned_mobile():
    unapproved = "".join(str(digit) for digit in range(10))

    reply = remove_unapproved_phone_numbers(f"You can reach me on {unapproved}.")

    assert unapproved not in reply
    assert reply == "You can reach me on."


def test_remove_unapproved_phone_numbers_keeps_exact_assigned_mobile_only():
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

    assert assigned in exact_reply
    assert same_digits_different_format not in formatted_reply
