"""The viewing-cancellation prompt must give a concrete, mundane withdrawal
reason (not the old vague 'something came up') and read as a clean close, not a
reschedule. Both channels share this prompt via generate_cancellation_message.
"""
from app.ai.prompts import build_cancel_viewing_prompt


def test_cancel_prompt_demands_concrete_reason_and_clean_close():
    p = build_cancel_viewing_prompt("LANDLORD: See you at 2pm tomorrow.").lower()
    # concrete mundane reasons offered
    assert "another property" in p or ("found" in p and "another" in p)
    assert "renew" in p or "stay in your current" in p
    assert "move has been delayed" in p or "plans have changed" in p
    # clean close: withdrawing, no reschedule
    assert "do not offer to reschedule" in p
    # still non-dramatic
    assert "never invent emergencies" in p
    # the old vague stock line is gone
    assert "something came up and i need to cancel the viewing today" not in p


def test_cancel_prompt_keeps_phone_and_placeholder_guards():
    p = build_cancel_viewing_prompt("LANDLORD: my number is 07123456789").lower()
    assert "never mention phone numbers" in p
    assert "placeholders" in p
