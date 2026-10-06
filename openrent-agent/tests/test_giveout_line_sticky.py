"""Moving an account to another WhatsApp line must not change the number a
landlord already received (2026-10-07, spreading accounts across 07783 / 07719).

Without pinning, the next reply in an old thread would offer a second, different
"partner's WhatsApp", and the "already shared" checks (blocked-number policy,
give-out salvage) would not recognise the number we gave, so it would re-give.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base
from app.openrent import viewing_lifecycle
from app.whatsapp.lines import pin_thread_giveout_number, thread_giveout_number

LINE1 = "07783129181"
LINE2 = "07719329803"
DEAD = "07599390221"
LIVE = {LINE1, LINE2}


def _us(text):
    return {"sender": "us", "message": text}


def _ll(text):
    return {"sender": "landlord", "message": text}


def test_thread_keeps_the_number_it_already_got():
    msgs = [_us("Hi, is it available?"), _ll("Yes"), _us(f"My partner's WhatsApp is {LINE1}.")]
    assert thread_giveout_number(msgs, LINE2, LIVE) == LINE1


def test_any_format_of_the_old_number_counts():
    for text in ("whatsapp 07783 129181", "+44 7783 129181", "+447783129181"):
        assert thread_giveout_number([_us(text)], LINE2, LIVE) == LINE1, text


def test_fresh_thread_gets_the_account_number():
    assert thread_giveout_number([_us("Hi, is it available?"), _ll("Yes")], LINE2, LIVE) == LINE2


def test_dead_line_is_not_sticky():
    assert thread_giveout_number([_us(f"WhatsApp {DEAD}")], LINE1, LIVE) == LINE1


def test_most_recent_live_number_wins():
    msgs = [_us(f"WhatsApp {LINE1}"), _ll("ok"), _us(f"Actually it's {LINE2}")]
    assert thread_giveout_number(msgs, LINE1, LIVE) == LINE2


def test_landlord_quoting_our_number_does_not_count():
    assert thread_giveout_number([_ll(f"is {LINE1} yours?")], LINE2, LIVE) == LINE2


def test_no_live_numbers_known_keeps_account_number():
    assert thread_giveout_number([_us(f"WhatsApp {LINE1}")], LINE2, set()) == LINE2


def test_pin_returns_same_persona_when_unchanged_and_a_copy_otherwise():
    persona = {"persona_name": "Jessica", "mobile_number": LINE2}
    assert pin_thread_giveout_number(persona, [], LIVE) is persona
    pinned = pin_thread_giveout_number(persona, [_us(f"WhatsApp {LINE1}")], LIVE)
    assert pinned["mobile_number"] == LINE1
    assert persona["mobile_number"] == LINE2, "the account persona must not be mutated"
    assert pin_thread_giveout_number(None, [], LIVE) is None
    no_mobile = {"persona_name": "Jessica"}
    assert pin_thread_giveout_number(no_mobile, [_us(LINE1)], LIVE) is no_mobile


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'lines.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    return Session


def test_get_giveout_numbers_lists_live_lines(db_session):
    with db_session() as s:
        for i, number in enumerate([LINE1, LINE1, LINE2, None, ""]):
            s.add(Account(email=f"a{i}@x.test", password="p", mobile_number=number))
        s.commit()
    assert repository.get_giveout_numbers() == {LINE1, LINE2}


def test_get_giveout_numbers_db_error_is_safe(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "SessionLocal", boom)
    assert repository.get_giveout_numbers() == set()


def test_salvage_gives_the_thread_its_original_number(monkeypatch):
    sent = []

    async def send_reply(page, text):
        sent.append(text)
        return True

    monkeypatch.setattr(viewing_lifecycle, "send_reply", send_reply)
    monkeypatch.setattr(viewing_lifecycle, "ensure_account_persona", lambda _id: {"mobile_number": LINE2})
    monkeypatch.setattr(viewing_lifecycle, "get_giveout_numbers", lambda: LIVE)
    for name in ("save_message", "mark_our_number_shared", "record_handoff_intent", "update_last_processed_message"):
        monkeypatch.setattr(viewing_lifecycle, name, lambda *a, **k: None)
    conv = SimpleNamespace(extracted_phone=None, our_number_shared_at=None, landlord_asked_phone_at=None,
                           viewing_datetime=None, landlord_attitude="responsive")
    msgs = [_us(f"My partner's WhatsApp is {LINE1}."), _ll("My number is (Number Removed)")]
    ok = asyncio.run(viewing_lifecycle._try_giveout_salvage(
        "T-S", conv, SimpleNamespace(id=23), msgs, msgs[-1]["message"], object(),
        require_landlord_asked=False,
    ))
    assert ok is True
    assert LINE1 in sent[0] and LINE2 not in sent[0]
