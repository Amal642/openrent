"""Overflow claiming: idle accounts take surplus listings from same-region
accounts (2026-09-30). Regression context: 270 open listings fleet-wide while
accounts whose neighbours scraped first sent 0/day."""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base, Listing, Location, SearchProfile

KEEP = repository.OVERFLOW_DONOR_KEEP


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'repo.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    with Session() as s:
        s.add_all([
            Location(name="Lewisham", term_value="Lewisham, London", region="South"),
            Location(name="Woolwich", term_value="Woolwich, Greater London", region="South"),
            Location(name="Harrow", term_value="Harrow, London", region="North"),
        ])
        s.commit()
    return Session


def _account(s, email, location, *, price_max=3150, failed=False, active_profile=True):
    acc = Account(email=email, password="", active=True, failed=failed)
    s.add(acc)
    s.flush()
    prof = SearchProfile(account_id=acc.id, location=location, price_min=1000, price_max=price_max,
                         bedrooms_min=0, bedrooms_max=4, area=10, active=active_profile)
    s.add(prof)
    s.flush()
    return acc.id, prof.id


def _listings(s, profile_id, n, *, age_hours=1, prefix="L", **kw):
    ids = []
    for i in range(n):
        l = Listing(listing_id=f"{prefix}{profile_id}-{i}", property_url=f"https://x/{profile_id}/{i}",
                    search_profile_id=profile_id,
                    first_seen=datetime.utcnow() - timedelta(hours=age_hours, minutes=i), **kw)
        s.add(l)
        s.flush()
        ids.append(l.id)
    s.commit()
    return ids


def test_starved_account_takes_only_healthy_donor_surplus(db):
    with db() as s:
        claimer, claimer_prof = _account(s, "c@x", "Lewisham, London")
        donor, donor_prof = _account(s, "d@x", "Woolwich, Greater London")
        _listings(s, donor_prof, KEEP + 3)

    listings, origins = repository.claim_overflow_listings(claimer, "w-c", limit=50)

    assert len(listings) == 3                      # donor keeps KEEP for itself
    with db() as s:
        moved = s.query(Listing).filter(Listing.id.in_(list(origins))).all()
        assert {l.search_profile_id for l in moved} == {claimer_prof}
        assert {l.processing_owner for l in moved} == {"w-c"}
        assert s.query(Listing).filter(Listing.search_profile_id == donor_prof).count() == KEEP
    assert all(o["origin_profile_id"] == donor_prof and o["origin_account_id"] == donor for o in origins.values())


def test_benched_donor_gives_everything_up_to_limit_newest_first(db):
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London")
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London", failed=True)
        ids = _listings(s, donor_prof, 5)          # i=0 is newest

    listings, _ = repository.claim_overflow_listings(claimer, "w-c", limit=3)

    assert [l.id for l in listings] == ids[:3]


def test_other_region_is_never_taken(db):
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London")          # South
        _, donor_prof = _account(s, "d@x", "Harrow, London", failed=True)  # North
        _listings(s, donor_prof, 5)

    assert repository.claim_overflow_listings(claimer, "w-c") == ([], {})


def test_claimed_old_or_known_over_cap_listings_are_skipped(db):
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London", price_max=3150)
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London", price_max=4000, failed=True)
        _listings(s, donor_prof, 1, prefix="busy", processing_owner="donor-worker",
                  processing_started_at=datetime.utcnow())
        _listings(s, donor_prof, 1, prefix="old", age_hours=24 * (repository.OVERFLOW_MAX_AGE_DAYS + 1))
        _listings(s, donor_prof, 1, prefix="dear", rent_pcm=3800)
        _listings(s, donor_prof, 1, prefix="sent", message_sent=True)
        _listings(s, donor_prof, 1, prefix="agent", skip_reason="agent")
        stale = _listings(s, donor_prof, 1, prefix="stale", processing_owner="dead-worker",
                          processing_started_at=datetime.utcnow() - timedelta(hours=2))
        ok = _listings(s, donor_prof, 1, prefix="ok", rent_pcm=2400)

    listings, _ = repository.claim_overflow_listings(claimer, "w-c", limit=50)

    assert sorted(l.id for l in listings) == sorted(stale + ok)


def test_claimer_without_active_profile_takes_nothing(db):
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London", active_profile=False)
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London", failed=True)
        _listings(s, donor_prof, 5)

    assert repository.claim_overflow_listings(claimer, "w-c") == ([], {})


def test_own_listings_are_never_overflow(db):
    with db() as s:
        claimer, claimer_prof = _account(s, "c@x", "Lewisham, London", failed=True)
        _listings(s, claimer_prof, 20)

    assert repository.claim_overflow_listings(claimer, "w-c") == ([], {})


def test_return_hands_back_unclaimed_and_is_conditional(db):
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London")
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London", failed=True)
        _listings(s, donor_prof, 3)
    listings, origins = repository.claim_overflow_listings(claimer, "w-c", limit=3)
    returned, sent, stolen = (l.id for l in listings)
    with db() as s:
        s.get(Listing, sent).message_sent = True
        s.get(Listing, stolen).processing_owner = "someone-else"
        s.commit()

    for pk in (returned, sent, stolen):
        repository.return_overflow_listing(pk, donor_prof, "w-c", reason="test")
    repository.return_overflow_listing(returned, donor_prof, "w-c", reason="again")  # idempotent

    with db() as s:
        back = s.get(Listing, returned)
        assert back.search_profile_id == donor_prof and back.processing_owner is None
        assert s.get(Listing, sent).search_profile_id != donor_prof        # never undo a send
        assert s.get(Listing, stolen).processing_owner == "someone-else"   # never clobber a claim


@pytest.mark.parametrize("metadata,fits", [
    ({"rent_pcm": None, "bedrooms": 2}, False),     # unknown rent -> not affordable-proven
    ({"rent_pcm": 3151, "bedrooms": 2}, False),
    ({"rent_pcm": 999, "bedrooms": 2}, False),
    ({"rent_pcm": 3150, "bedrooms": 2}, True),
    ({"rent_pcm": 2000, "bedrooms": None}, True),
    ({"rent_pcm": 2000, "bedrooms": 5}, False),
])
def test_fits_band(metadata, fits):
    band = {"price_min": 1000, "price_max": 3150, "bedrooms_min": 0, "bedrooms_max": 4}
    assert repository.overflow_listing_fits_band(metadata, band) is fits


def test_send_path_returns_every_unsent_overflow_listing_even_on_error(monkeypatch):
    from scripts import process_listings as pl

    class Acc:
        id = 30
        email = "c@x"

    fake = [type("L", (), {"id": pk})() for pk in (11, 12)]
    origins = {11: {"origin_profile_id": 7, "origin_account_id": 35},
               12: {"origin_profile_id": 8, "origin_account_id": 24}}
    returned = []
    monkeypatch.setattr(pl, "is_uk_outreach_window", lambda: True)
    monkeypatch.setattr(pl, "can_send_message", lambda _id: True)
    monkeypatch.setattr(pl, "is_outreach_due", lambda _id: True)
    monkeypatch.setattr(pl, "ensure_account_persona", lambda _id: {})
    monkeypatch.setattr(pl, "claim_uncontacted_listings", lambda *a, **k: [])
    monkeypatch.setattr(pl, "claim_overflow_listings", lambda *a, **k: (fake, origins))
    monkeypatch.setattr(pl, "return_overflow_listing",
                        lambda pk, prof, owner, reason="": returned.append((pk, prof, owner)))

    async def boom(*a, **k):
        raise RuntimeError("browser died")
    monkeypatch.setattr(pl, "_process_claimed_listings", boom)

    with pytest.raises(RuntimeError):
        asyncio.run(pl.process_account_listings(Acc(), page=None, worker_id="w-30"))
    assert sorted(returned) == [(11, 7, "w-30"), (12, 8, "w-30")]


def test_send_path_does_not_overflow_when_own_inventory_exists(monkeypatch):
    from scripts import process_listings as pl

    class Acc:
        id = 30
        email = "c@x"

    called = []
    monkeypatch.setattr(pl, "is_uk_outreach_window", lambda: True)
    monkeypatch.setattr(pl, "can_send_message", lambda _id: True)
    monkeypatch.setattr(pl, "is_outreach_due", lambda _id: True)
    monkeypatch.setattr(pl, "ensure_account_persona", lambda _id: {})
    monkeypatch.setattr(pl, "claim_uncontacted_listings", lambda *a, **k: [object()])
    monkeypatch.setattr(pl, "claim_overflow_listings", lambda *a, **k: called.append(1) or ([], {}))

    async def ok(*a, **k):
        return 0, 0, 0, 0
    monkeypatch.setattr(pl, "_process_claimed_listings", ok)

    asyncio.run(pl.process_account_listings(Acc(), page=None, worker_id="w-30"))
    assert called == []


def test_scraper_donor_gives_everything(db):
    # 2026-10-06: restricted accounts were set to daily_limit 0 (search only).
    # They will never send, so the keep-a-day rule must not lock their finds.
    with db() as s:
        claimer, _ = _account(s, "c@x", "Lewisham, London")
        scraper, scraper_prof = _account(s, "s@x", "Woolwich, Greater London")
        s.get(Account, scraper).daily_limit = 0
        s.commit()
        _listings(s, scraper_prof, 5)

    listings, _ = repository.claim_overflow_listings(claimer, "w-c", limit=50)

    assert len(listings) == 5


def test_own_queue_is_claimed_newest_first(db):
    # 2026-10-07: claim_uncontacted_listings had no ORDER BY, so fresh listings
    # waited behind week-old ones. Enquiries in a listing's first 3 days captured
    # ~42% of numbers vs ~33% after.
    with db() as s:
        acc, prof = _account(s, "own@x", "Lewisham, London")
        old = _listings(s, prof, 3, age_hours=24 * 8, prefix="O")
        new = _listings(s, prof, 3, age_hours=2, prefix="N")

    claimed = repository.claim_uncontacted_listings(acc, "w-own", limit=4)

    assert [l.id for l in claimed] == new + old[:1]


def test_own_queue_ties_prefer_the_higher_openrent_id(db):
    seen = datetime.utcnow() - timedelta(hours=1)
    with db() as s:
        acc, prof = _account(s, "tie@x", "Lewisham, London")
        for lid in ("999999", "3064996", "3065000"):
            s.add(Listing(listing_id=lid, property_url=f"https://x/{lid}", search_profile_id=prof, first_seen=seen))
        s.commit()

    claimed = repository.claim_uncontacted_listings(acc, "w-tie", limit=3)

    assert [l.listing_id for l in claimed] == ["3065000", "3064996", "999999"]
