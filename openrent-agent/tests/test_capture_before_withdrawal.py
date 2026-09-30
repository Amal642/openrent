"""_capture_phone_before_withdrawal: last full extraction before a viewing in
its cancel window is handed to the withdrawal sweep (which never extracts)."""
import asyncio

from scripts import process_replies as pr


def _patch(monkeypatch, *, revealed=False, after_reveal=None, regex=None, ai=None, exists=False):
    saved = []

    async def reveal(_page):
        return revealed

    async def extract(_page):
        return after_reveal or []

    monkeypatch.setattr(pr, "reveal_hidden_phone_number", reveal)
    monkeypatch.setattr(pr, "extract_conversation", extract)
    monkeypatch.setattr(pr, "get_landlord_messages", lambda msgs: [m["message"] for m in msgs])
    monkeypatch.setattr(pr, "regex_extract_phone", lambda texts: regex(texts) if callable(regex) else regex)
    monkeypatch.setattr(pr, "ai_extract_phone", lambda texts: ai)
    monkeypatch.setattr(pr, "phone_exists", lambda p: exists)
    monkeypatch.setattr(pr, "save_phone_number", lambda tid, p: saved.append((tid, p)))
    monkeypatch.setattr(pr, "_log_playbook_ab_phone_capture", lambda tid: None)
    return saved


MSGS = [{"sender": "landlord", "message": "see you at 2"}]


def test_obfuscated_number_found_by_ai_is_saved(monkeypatch):
    saved = _patch(monkeypatch, regex=None, ai="07911 123456")
    got = asyncio.run(pr._capture_phone_before_withdrawal("T1", object(), MSGS))
    assert got == "07911123456"
    assert saved == [("T1", "07911123456")]


def test_hidden_number_revealed_then_regex(monkeypatch):
    revealed_msgs = [{"sender": "landlord", "message": "07922 654321"}]
    saved = _patch(
        monkeypatch,
        revealed=True,
        after_reveal=revealed_msgs,
        regex=lambda texts: "07922654321" if "07922 654321" in texts else None,
    )
    got = asyncio.run(pr._capture_phone_before_withdrawal("T1", object(), MSGS))
    assert got == "07922654321"
    assert saved == [("T1", "07922654321")]


def test_duplicate_number_is_not_saved(monkeypatch):
    saved = _patch(monkeypatch, regex="07911123456", exists=True)
    assert asyncio.run(pr._capture_phone_before_withdrawal("T1", object(), MSGS)) is None
    assert saved == []


def test_redacted_or_nothing_saves_nothing(monkeypatch):
    saved = _patch(monkeypatch, regex=None, ai="(Number Removed)")
    assert asyncio.run(pr._capture_phone_before_withdrawal("T1", object(), MSGS)) is None
    assert saved == []


def test_errors_never_raise(monkeypatch):
    _patch(monkeypatch)

    async def boom(_page):
        raise RuntimeError("page closed")

    monkeypatch.setattr(pr, "reveal_hidden_phone_number", boom)
    assert asyncio.run(pr._capture_phone_before_withdrawal("T1", object(), MSGS)) is None
