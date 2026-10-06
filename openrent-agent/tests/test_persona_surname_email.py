"""Accounts whose OpenRent profile carries a real full name store their surname
and mailbox (persona_surname / persona_email). Legacy accounts (both NULL) keep
the pool surname and never give out an email."""
from app.ai.prompts import _SURNAME_POOL, build_human_renter_reply_prompt, persona_surnames
from app.ai.validators import is_valid_reply

LEGACY = {
    "persona_name": "Claire",
    "persona_partner_name": "Marcus",
    "persona_type": "engineer_consultant_couple",
    "persona_job": "Management Consultant",
    "persona_partner_job": "IT Consultant",
    "mobile_number": "07783129181",
}
REAL = {
    **LEGACY,
    "persona_name": "Jack",
    "persona_partner_name": "Amy",
    "persona_surname": "Turner",
    "persona_email": "jturner_92@outlook.com",
}


def test_legacy_surname_unchanged_by_new_code():
    # Same seed as before the change: legacy personas must keep the surname
    # they have already given landlords.
    sur = persona_surnames(LEGACY)
    assert sur["primary"] in _SURNAME_POOL
    assert sur["partner"] in _SURNAME_POOL
    assert sur == persona_surnames({**LEGACY, "persona_surname": None, "persona_email": None})
    assert sur == persona_surnames({**LEGACY, "persona_surname": "  "})


def test_stored_surname_wins_and_partner_differs():
    sur = persona_surnames(REAL)
    assert sur["primary"] == "Turner"
    assert sur["partner"] in _SURNAME_POOL
    assert sur["partner"].lower() != "turner"


def test_partner_never_collides_with_stored_surname():
    for name in _SURNAME_POOL:
        sur = persona_surnames({**REAL, "persona_surname": name})
        assert sur["primary"] == name
        assert sur["partner"] != name


def test_prompt_uses_real_full_name():
    prompt = build_human_renter_reply_prompt(conversation="LANDLORD: what are your full names?", persona=REAL)
    assert "Jack Turner" in prompt


def test_prompt_gives_email_only_when_stored():
    real = build_human_renter_reply_prompt(conversation="LANDLORD: what's your email?", persona=REAL)
    assert "jturner_92@outlook.com" in real
    legacy = build_human_renter_reply_prompt(conversation="LANDLORD: what's your email?", persona=LEGACY)
    assert "outlook.com" not in legacy
    assert "you do not have an email set up" in legacy


def test_validator_allows_only_own_email():
    ok = "Sure, it's jturner_92@outlook.com"
    assert is_valid_reply(ok, allowed_email="jturner_92@outlook.com") is True
    assert is_valid_reply("Sure, it's JTurner_92@Outlook.com.", allowed_email="jturner_92@outlook.com") is True
    # No mailbox stored -> any email is still rejected (old behaviour).
    assert is_valid_reply(ok) is False
    # A different / invented address is rejected even when one is allowed.
    assert is_valid_reply("Sure, it's jack@example.com", allowed_email="jturner_92@outlook.com") is False
    assert is_valid_reply(
        "Mine is jturner_92@outlook.com, or my partner's amy@gmail.com",
        allowed_email="jturner_92@outlook.com",
    ) is False
