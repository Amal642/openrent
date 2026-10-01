"""One story on both sides of the give-out (2026-09-30).

OpenRent side said "my WhatsApp" while the WhatsApp line answered as a husband
("my wife handles our OpenRent messages"), and the property-ask treated the
landlord as a prospective tenant. Both sides now say the number is the
PARTNER's (gender-neutral: some personas' partners are women).
"""
import pytest

from app.ai import personas, prompts
from app.whatsapp import reply


@pytest.mark.parametrize("message,expected", [
    ("Hello, is this Nicola from Openrent?", "Nicola"),
    ("Hi Sarah, its Mark about the flat", "Sarah"),
    ("Hello are you Katherine?", "Katherine"),
    ("Am I speaking with Olivia?", "Olivia"),
    ("Hey Laura!", "Laura"),
    ("Hi. Are you there", None),
    ("Hi there, is the viewing on?", None),
    ("This is Mark, the landlord", None),
    ("hi, you messaged me about my flat", None),
    ("Is this the right number for the flat?", None),
])
def test_name_asked_for(message, expected):
    assert reply._name_asked_for([{"direction": "inbound", "message": message}]) == expected


def test_name_asked_for_uses_latest_inbound_only():
    history = [
        {"direction": "inbound", "message": "Hi Sarah"},
        {"direction": "outbound", "message": "Hi, which property is this?"},
        {"direction": "inbound", "message": "The one on Elm Road"},
    ]
    assert reply._name_asked_for(history) is None


class _FakeClient:
    def __init__(self):
        self.prompts = []

        class _Completions:
            def create(inner, **kwargs):
                self.prompts.append(kwargs["messages"][0]["content"])

                class _Msg:
                    content = "ok"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_property_ask_prompt_frames_landlord_and_partner(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(reply, "_client", fake)

    reply.build_property_ask(None, [{"direction": "inbound", "message": "Hi. Are you there"}])
    prompt = fake.prompts[-1]
    assert "landlords" in prompt and "THEIR property" in prompt
    assert "my partner" in prompt
    assert "wife" not in prompt and "husband" not in prompt
    assert "partner here" not in prompt  # no name asked -> no scripted intro

    reply.build_property_ask(None, [{"direction": "inbound", "message": "Hello, is this Nicola from Openrent?"}])
    assert "\"Hi, it's Nicola's partner here\"" in fake.prompts[-1]


def test_property_ask_fallback_says_partner(monkeypatch):
    class _Broken:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("down")

    monkeypatch.setattr(reply, "_client", _Broken)
    text = reply.build_property_ask(None, [])
    assert "my partner" in text and "wife" not in text


@pytest.mark.parametrize("attitude", sorted(personas.LANDLORD_ATTITUDES))
def test_phone_share_templates_are_partner_neutral(attitude):
    for _ in range(10):
        text = personas.generate_phone_share_reply({"mobile_number": "07783129181"}, attitude)
        assert "partner" in text.lower()
        assert "husband" not in text.lower()
        assert " he " not in f" {text.lower()} " and " him " not in f" {text.lower()} "
        assert "07783129181" in text


def test_live_reply_prompt_gives_partners_whatsapp(monkeypatch):
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "all")
    persona = {
        "persona_name": "Nicola", "persona_partner_name": "Chris", "persona_job": "Structural Engineer",
        "persona_partner_job": "Civil Engineer", "persona_type": "engineer_consultant_couple",
        "mobile_number": "07783129181",
    }
    prompt = prompts.build_human_renter_reply_prompt(
        conversation="LANDLORD: Can you send me your number?", persona=persona, property=None, place="Reading",
    )
    assert "partner's WhatsApp number: 07783129181" in prompt
    assert "Give them your WhatsApp number" not in prompt
    assert "husband" not in prompt.lower()


def test_property_ask_prompt_explains_who_we_are(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(reply, "_client", fake)
    reply.build_property_ask(None, [{"direction": "inbound", "message": "Hi, who is this?"}])
    prompt = fake.prompts[-1]
    assert "ask who you are" in prompt
    assert "gave you this number" in prompt
