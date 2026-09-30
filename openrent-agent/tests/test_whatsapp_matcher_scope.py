"""WhatsApp matching only considers listings we actually messaged: a landlord
can only have our WhatsApp number if we contacted them. Scoring every listing
produced matches with no conversation (lead marked acquired, never exported)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Listing
from app.whatsapp import matcher


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(matcher, "SessionLocal", Session)
    with Session() as s:
        s.add_all([
            Listing(listing_id="SENT", property_url="u1", landlord_name="Priya Sharma",
                    property_address="12 Elm Road, Ealing", message_sent=True, thread_id="T-SENT"),
            Listing(listing_id="NEVER", property_url="u2", landlord_name="Priya Sharma",
                    property_address="12 Elm Road, Ealing", message_sent=False),
        ])
        s.commit()
    return Session


def _ids(db, rows):
    with db() as s:
        by_pk = {l.id: l.listing_id for l in s.query(Listing).all()}
    return {by_pk[r["listing_id"]] for r in rows}


def test_evidence_match_ignores_never_messaged_listings(db):
    candidates, _ = matcher.match_by_evidence(["Priya Sharma"], ["12 Elm Road"])
    assert candidates and _ids(db, candidates) == {"SENT"}


def test_name_match_ignores_never_messaged_listings(db):
    assert _ids(db, matcher.match_landlord_by_name("Priya Sharma")) == {"SENT"}


def test_property_match_ignores_never_messaged_listings(db):
    best, score = matcher.match_landlord_by_property("12 Elm Road Ealing")
    assert best is not None and _ids(db, [best]) == {"SENT"}
