"""A landlord whose number OpenRent redacted ("(Number Removed)") must get a
reply, and the thread must NOT be marked PHONE_ACQUIRED without a phone.

Before 2026-09-30 the loop logged PHONE_NORMALISE_EMPTY, sent nothing, and
re-processed the thread every sweep (4 landlords / 98 loops in 7 days on prod).
"""
import asyncio

from scripts import process_replies
from app.db.status import PHONE_ACQUIRED
from test_playbook_ab import DummyAccount, _patch_process_flow

REDACTED = "Sure - I'm (Number Removed) . See you later."


def _run(monkeypatch, tmp_path, *, regex=None, ai=None):
    sent, statuses, saved = [], [], []
    _patch_process_flow(
        monkeypatch, REDACTED, tmp_path / "ab.jsonl", sent, expect_assignment=False
    )
    monkeypatch.delenv("PLAYBOOK_AB_ENABLED", raising=False)
    monkeypatch.setattr(process_replies, "regex_extract_phone", lambda _t: regex)
    monkeypatch.setattr(process_replies, "ai_extract_phone", lambda _t: ai)
    monkeypatch.setattr(
        process_replies, "update_conversation_status", lambda tid, st: statuses.append(st)
    )
    monkeypatch.setattr(
        process_replies, "save_phone_number", lambda *a: saved.append(a)
    )
    monkeypatch.setattr(process_replies, "detect_short_term_tenancy", lambda _m: False)
    monkeypatch.setattr(process_replies, "landlord_wants_video_call", lambda _m: False)
    monkeypatch.setattr(
        process_replies,
        "generate_reply",
        lambda *a, **k: ("Ah it came through as removed on here! My husband's WhatsApp is 07743 722832.", None),
    )
    asyncio.run(process_replies.process_account_replies(DummyAccount(), object()))
    return sent, statuses, saved


def test_ai_extractor_returning_redaction_text_still_replies(monkeypatch, tmp_path):
    sent, statuses, saved = _run(monkeypatch, tmp_path, ai="(Number Removed)")
    assert len(sent) == 1, "landlord must get a reply, not silence"
    assert PHONE_ACQUIRED not in statuses
    assert saved == []


def test_regex_invalid_number_still_replies(monkeypatch, tmp_path):
    sent, statuses, saved = _run(monkeypatch, tmp_path, regex="0797335323")  # 10 digits
    assert len(sent) == 1
    assert PHONE_ACQUIRED not in statuses
    assert saved == []


def test_valid_ai_number_is_still_captured(monkeypatch, tmp_path):
    monkeypatch.setattr(process_replies, "phone_exists", lambda _p: False)
    monkeypatch.setattr(process_replies, "_log_playbook_ab_phone_capture", lambda _t: None)

    async def no_dt(*_a, **_k):
        return None

    monkeypatch.setattr(process_replies, "_try_save_viewing_datetime", no_dt)
    monkeypatch.setattr(process_replies, "count_phones_today", lambda _id: 1)
    monkeypatch.setattr(process_replies, "update_conversation_stage", lambda *a: None)
    sent, statuses, saved = _run(monkeypatch, tmp_path, ai="07911 123456")
    assert PHONE_ACQUIRED in statuses
    assert saved and saved[0][1] == "07911123456"
    assert sent == [], "a captured number is handled by the capture path, not a normal reply"
