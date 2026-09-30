"""All "today" counts and per-day buckets follow the UK calendar day.

Timestamps are stored as naive UTC. In summer (BST) UK midnight is 23:00 UTC
the previous day, so an event at 00:30 UK must count for the UK day, not the
previous UTC day.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base, Conversation, Listing, Message, SearchProfile
from app.utils import scheduling
from app.utils.scheduling import UK_TZ, uk_day_start_utc, utc_naive_to_uk_date


def test_uk_day_start_in_summer_and_winter():
    assert uk_day_start_utc(date(2026, 9, 30)) == datetime(2026, 9, 29, 23, 0)  # BST
    assert uk_day_start_utc(date(2026, 12, 1)) == datetime(2026, 12, 1, 0, 0)   # GMT


def test_dst_change_days_are_exact():
    # 2026-10-25 is the BST->GMT switch: that UK day is 25 hours long.
    start = uk_day_start_utc(date(2026, 10, 25))
    end = uk_day_start_utc(date(2026, 10, 26))
    assert end - start == timedelta(hours=25)


def test_utc_timestamp_maps_to_uk_date():
    assert utc_naive_to_uk_date(datetime(2026, 9, 29, 23, 30)) == date(2026, 9, 30)
    assert utc_naive_to_uk_date(datetime(2026, 12, 1, 23, 30)) == date(2026, 12, 1)
    assert utc_naive_to_uk_date(None) is None


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    # Freeze "now" at 09:00 UK on 2026-09-30 (08:00 UTC).
    frozen = datetime(2026, 9, 30, 9, 0, tzinfo=UK_TZ)
    monkeypatch.setattr(scheduling, "uk_now", lambda: frozen)
    monkeypatch.setattr(repository, "uk_now", lambda: frozen)
    return Session


def _seed(Session):
    with Session() as s:
        acc = Account(email="a@x.test", password="", session_file="s.json", daily_limit=8)
        s.add(acc)
        s.flush()
        prof = SearchProfile(account_id=acc.id, location="London")
        s.add(prof)
        s.flush()
        lst = Listing(listing_id="L1", property_url="u1", search_profile_id=prof.id, message_sent=True)
        s.add(lst)
        s.flush()
        # 00:30 UK on 2026-09-30 == 23:30 UTC on 2026-09-29
        early = datetime(2026, 9, 29, 23, 30)
        conv = Conversation(thread_id="T1", listing_id=lst.id, extracted_phone="07911123456",
                            phone_found_at=early)
        s.add(conv)
        s.flush()
        s.add(Message(conversation_id=conv.id, direction="outbound", content="hi", created_at=early))
        # 23:30 UK on 2026-09-29 == 22:30 UTC: belongs to the PREVIOUS UK day
        conv2 = Conversation(thread_id="T2", listing_id=lst.id, extracted_phone="07922654321",
                             phone_found_at=datetime(2026, 9, 29, 22, 30))
        s.add(conv2)
        s.flush()
        s.add(Message(conversation_id=conv2.id, direction="outbound", content="hi",
                      created_at=datetime(2026, 9, 29, 22, 30)))
        s.commit()
        return acc.id


def test_phones_today_counts_uk_day(db):
    acc_id = _seed(db)
    assert repository.count_phones_today(acc_id) == 1


def test_outreach_on_day_uses_uk_day(db):
    _seed(db)
    assert repository.count_new_outreach_on_day(date(2026, 9, 30)) == 1
    assert repository.count_new_outreach_on_day(date(2026, 9, 29)) == 1
    assert repository.count_new_outreach_on_day() == 1  # default = UK today


def test_daily_limit_counter_not_reset_within_same_uk_day(db):
    acc_id = _seed(db)
    with db() as s:
        acc = s.get(Account, acc_id)
        acc.messages_sent_today = 3
        acc.messages_sent_reset_at = datetime(2026, 9, 29, 23, 30)  # 00:30 UK today
        s.commit()
    repository.can_send_message(acc_id)
    with db() as s:
        assert s.get(Account, acc_id).messages_sent_today == 3
