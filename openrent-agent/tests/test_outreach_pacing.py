"""Outreach pacing must fit the whole daily_limit inside the window.

2026-10-02: every account sent 7 of its 8, because the last send was planned
at the window end and any worker delay pushed it past the cutoff."""
import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base
from app.utils import scheduling

UK = scheduling.UK_TZ


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'repo.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    return Session


@pytest.mark.parametrize("seed", range(20))
def test_all_eight_daily_sends_fit_before_midnight(db, monkeypatch, seed):
    random.seed(seed)
    with db() as s:
        acc = Account(email="a@x", password="", active=True, daily_limit=8, messages_sent_today=0)
        s.add(acc)
        s.commit()
        account_id = acc.id

    clock = {"now": datetime(2026, 10, 2, 8, 5, tzinfo=UK)}
    monkeypatch.setattr(scheduling, "uk_now", lambda: clock["now"])

    sent_at = []
    while scheduling.is_uk_outreach_window(clock["now"]) and len(sent_at) < 8:
        sent_at.append(clock["now"])
        with db() as s:
            s.get(Account, account_id).messages_sent_today = len(sent_at)
            s.commit()
        repository.set_next_outreach_at(account_id)
        with db() as s:
            nxt = s.get(Account, account_id).next_outreach_at
        # Workers pick the account up some minutes after it becomes due.
        delay = timedelta(minutes=random.uniform(5, 25))
        clock["now"] = nxt.replace(tzinfo=timezone.utc).astimezone(UK) + delay

    assert len(sent_at) == 8, [t.strftime("%H:%M") for t in sent_at]
    assert sent_at[-1].hour < 23
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(sent_at, sent_at[1:])]
    assert min(gaps) >= repository.OUTREACH_GAP_MIN_MINUTES
