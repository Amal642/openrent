"""Cost-control: internal classification/extraction calls must use the cheaper
OPENAI_UTILITY_MODEL, while landlord-facing reply generation stays on the
quality OPENAI_REPLY_MODEL. Guards against accidentally routing either way.
"""
import json
import types

from app.config import settings
from app.ai import replies, extractors


def _fake_response(content):
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


def _patch(monkeypatch, module, content):
    captured = {}

    def fake_create(**kwargs):
        captured["model"] = kwargs.get("model")
        return _fake_response(content)

    monkeypatch.setattr(module.client.chat.completions, "create", fake_create)
    return captured


def test_utility_model_defaults_to_cheaper_mini():
    assert settings.OPENAI_UTILITY_MODEL == "gpt-4o-mini"
    # Reply model must remain the quality model.
    assert settings.OPENAI_REPLY_MODEL == "gpt-4.1-mini"


def test_viewing_detector_uses_utility_model(monkeypatch):
    captured = _patch(
        monkeypatch, replies,
        json.dumps({"viewing_arranged": False, "viewing_datetime": None, "reason": "x"}),
    )
    replies.ai_detect_viewing_arranged([{"sender": "landlord", "message": "hi"}])
    assert captured["model"] == settings.OPENAI_UTILITY_MODEL


def test_short_term_detector_uses_utility_model(monkeypatch):
    captured = _patch(
        monkeypatch, replies,
        json.dumps({"is_short_term": False, "reason": "x"}),
    )
    replies.detect_short_term_tenancy([{"sender": "landlord", "message": "hi"}])
    assert captured["model"] == settings.OPENAI_UTILITY_MODEL


def test_phone_extractor_uses_utility_model(monkeypatch):
    captured = _patch(monkeypatch, extractors, "NONE")
    extractors.ai_extract_phone(["no number here"])
    assert captured["model"] == settings.OPENAI_UTILITY_MODEL
