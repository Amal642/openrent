from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import (
    Account,
    Base,
    Conversation,
    Listing,
    SearchProfile,
)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "repo.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def _make_account(session, *, email):
    account = Account(email=email, password="", session_file="s.json", active=True)
    session.add(account)
    session.flush()
    profile = SearchProfile(account_id=account.id, location="Woolwich, Greater London")
    session.add(profile)
    session.flush()
    return account.id, profile.id


def _add_conversations(session, profile_id, *, count, replied, phones, age_days=1):
    created = datetime.utcnow() - timedelta(days=age_days)
    for i in range(count):
        listing = Listing(
            listing_id=f"L{profile_id}-{i}",
            property_url=f"https://example.com/{profile_id}/{i}",
            search_profile_id=profile_id,
        )
        session.add(listing)
        session.flush()
        conv = Conversation(
            thread_id=f"T{profile_id}-{i}",
            listing_id=listing.id,
            created_at=created,
            last_processed_message="landlord replied" if i < replied else None,
            extracted_phone=f"07{profile_id:03d}{i:06d}" if i < phones else None,
        )
        session.add(conv)
    session.commit()


def test_soft_banned_account_is_benched(db_session):
    with db_session() as session:
        acc_id, profile_id = _make_account(session, email="dead@example.com")
        # 40 convos, 20% reply, 0% phone -> soft-ban signature.
        _add_conversations(session, profile_id, count=40, replied=8, phones=0)

    repository.detect_and_mark_degraded_accounts()

    with db_session() as session:
        account = session.query(Account).filter_by(id=acc_id).one()
        assert account.failed is True
        assert account.failure_reason and "Degraded" in account.failure_reason


def test_healthy_account_not_benched(db_session):
    with db_session() as session:
        acc_id, profile_id = _make_account(session, email="healthy@example.com")
        # 40 convos, 80% reply, 40% phone -> healthy.
        _add_conversations(session, profile_id, count=40, replied=32, phones=16)

    repository.detect_and_mark_degraded_accounts()

    with db_session() as session:
        account = session.query(Account).filter_by(id=acc_id).one()
        assert account.failed is False


def test_low_volume_account_not_benched(db_session):
    with db_session() as session:
        acc_id, profile_id = _make_account(session, email="quiet@example.com")
        # Below the minimum-conversation floor: 0 replies but too few to judge.
        _add_conversations(session, profile_id, count=5, replied=0, phones=0)

    repository.detect_and_mark_degraded_accounts()

    with db_session() as session:
        account = session.query(Account).filter_by(id=acc_id).one()
        assert account.failed is False


def test_replies_but_no_phone_not_benched(db_session):
    """Good reply rate but poor closing is a prompt problem, not a dead account."""
    with db_session() as session:
        acc_id, profile_id = _make_account(session, email="talks@example.com")
        _add_conversations(session, profile_id, count=40, replied=30, phones=0)

    repository.detect_and_mark_degraded_accounts()

    with db_session() as session:
        account = session.query(Account).filter_by(id=acc_id).one()
        assert account.failed is False


def test_old_conversations_ignored(db_session):
    """Collapse must be recent: conversations outside the window don't count."""
    with db_session() as session:
        acc_id, profile_id = _make_account(session, email="stale@example.com")
        _add_conversations(
            session, profile_id, count=40, replied=4, phones=0, age_days=30
        )

    repository.detect_and_mark_degraded_accounts()

    with db_session() as session:
        account = session.query(Account).filter_by(id=acc_id).one()
        assert account.failed is False


def test_scheduler_skips_failed_account(monkeypatch):
    from app.services import account_scheduler

    monkeypatch.setattr(account_scheduler, "is_account_on_cooldown", lambda _id: False)

    class FakeProxy:
        is_active = True
        health_status = "ok"

    class FakeAccount:
        def __init__(self, id, failed):
            self.id = id
            self.email = f"a{id}@example.com"
            self.failed = failed
            self.permanently_failed = False
            self.worker_status = "idle"
            self.proxy_id = id
            self.proxy = FakeProxy()
            self.proxy_status = "ok"
            self.cooldown_until = None
            self.session_status = "active"
            self.session_auth_failures = 0
            self.worker_last_heartbeat = None

    healthy = FakeAccount(1, failed=False)
    benched = FakeAccount(2, failed=True)

    selected = account_scheduler._select_accounts([healthy, benched])
    selected_ids = {a.id for a in selected}
    assert 1 in selected_ids
    assert 2 not in selected_ids
