"""delete_stale_uncontacted_listings must skip listings still referenced by a
conversation or WhatsApp contact (FK, no cascade). One referenced row made the
whole daily batch fail on prod since at least 2026-09-25."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Base, Conversation, Listing, WhatsAppContact


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # enforce FKs like Postgres does
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    return Session


def _listing(s, lid, *, days_old, sent=False):
    l = Listing(listing_id=lid, property_url=f"u/{lid}", message_sent=sent,
                first_seen=datetime.utcnow() - timedelta(days=days_old))
    s.add(l)
    s.flush()
    return l


def test_cleanup_deletes_stale_but_skips_referenced(db):
    with db() as s:
        _listing(s, "OLD-FREE", days_old=40)
        ref_wa = _listing(s, "OLD-WA", days_old=40)
        ref_conv = _listing(s, "OLD-CONV", days_old=40)
        _listing(s, "NEW", days_old=5)
        _listing(s, "OLD-SENT", days_old=40, sent=True)
        s.add(WhatsAppContact(phone_number="447911123456", listing_id=ref_wa.id))
        s.add(Conversation(thread_id="T1", listing_id=ref_conv.id))
        s.commit()

    deleted = repository.delete_stale_uncontacted_listings(30)

    assert deleted == 1
    with db() as s:
        left = {l.listing_id for l in s.query(Listing).all()}
    assert left == {"OLD-WA", "OLD-CONV", "NEW", "OLD-SENT"}
