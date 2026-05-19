from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base, Conversation, Listing, SearchProfile


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "repo.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def test_save_phone_number_sets_acquisition_timestamp(db_session):
    with db_session() as session:
        account = Account(email="a@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        account_id = account.id
        profile = SearchProfile(account_id=account.id, location="Leeds")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="L1",
            property_url="https://example.com/1",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(
            thread_id="T1",
            listing_id=listing.id,
            last_message_at=datetime.utcnow() - timedelta(days=2),
        )
        session.add(conversation)
        session.commit()

    repository.save_phone_number("T1", "07123456789")

    with db_session() as session:
        conversation = session.query(Conversation).filter_by(thread_id="T1").one()
        assert conversation.phone_found is True
        assert conversation.phone_found_at is not None

    assert repository.count_phones_today(account_id) == 1


def test_mark_listing_skipped_is_not_processing_failure(db_session):
    with db_session() as session:
        listing = Listing(
            listing_id="L2",
            property_url="https://example.com/2",
            search_profile_id=None,
        )
        session.add(listing)
        session.commit()
        listing_id = listing.id

    repository.mark_listing_skipped(listing_id, reason="not_contactable")

    with db_session() as session:
        listing = session.query(Listing).filter_by(id=listing_id).one()
        assert listing.skip_reason == "not_contactable"
        assert listing.processing_failed is False
