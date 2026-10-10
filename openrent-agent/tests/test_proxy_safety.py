"""2026-10-06: a Decodo IP swap made Static 7-10 fail for a few minutes; the
failover moved 13 accounts onto placeholder rows (empty host / port 0 / URL in
host) that resolve to NO proxy. Failover must skip such rows."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base, Proxy


@pytest.mark.parametrize("host,port,ok", [
    ("isp.decodo.com", 10007, True),
    ("", 0, False),
    (None, 10007, False),
    ("http://gate.decodo.com:10004", 0, False),
    ("isp.decodo.com", 0, False),
])
def test_proxy_row_is_usable(host, port, ok):
    assert repository.proxy_row_is_usable(SimpleNamespace(host=host, port=port)) is ok


def test_failover_never_picks_placeholder_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    with Session() as s:
        failing = Proxy(name="Static 7", host="isp.decodo.com", port=10007, is_active=True, health_status="down")
        empty = Proxy(name="Proxy 11", host="", port=0, is_active=True, health_status=None)
        url_in_host = Proxy(name="Proxy 12", host="http://gate.decodo.com:10004", port=0, is_active=True)
        good = Proxy(name="Static 4", host="isp.decodo.com", port=10004, is_active=True, health_status="ok")
        s.add_all([failing, empty, url_in_host, good])
        s.commit()
        # The good proxy is the most loaded, so the old code picked a placeholder.
        for i in range(3):
            s.add(Account(email=f"a{i}@x", password="", proxy_id=good.id))
        s.commit()
        failing_id, good_id = failing.id, good.id

    assert repository.find_replacement_proxy(failing_id) == good_id


@pytest.fixture()
def split_db(tmp_path, monkeypatch):
    """Proxy split (2026-10-10): senders max 2 per proxy and never with a
    scraper (daily_limit 0); scrapers only with other scrapers."""
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}")
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    n = iter(range(1000))

    def proxy(**kw):
        with Session() as s:
            fields = {"is_active": True, "health_status": "ok", **kw}
            p = Proxy(name="p", host="isp.decodo.com", port=10000 + next(n), **fields)
            s.add(p)
            s.commit()
            return p.id

    def account(proxy_id, daily_limit, **kw):
        with Session() as s:
            a = Account(email=f"a{next(n)}@x", password="", proxy_id=proxy_id, daily_limit=daily_limit, **kw)
            s.add(a)
            s.commit()
            return a.id

    return SimpleNamespace(proxy=proxy, account=account)


def test_sender_never_moves_onto_scraper_proxy(split_db):
    failing = split_db.proxy(health_status="down")
    scraper_px = split_db.proxy()   # least loaded: the old code picked it
    sender_px = split_db.proxy()
    mover = split_db.account(failing, 8)
    split_db.account(scraper_px, 0)
    split_db.account(sender_px, 8)
    split_db.account(sender_px, None)  # NULL limit = default sender
    assert repository.find_replacement_proxy(failing, account_id=mover) is None
    third = split_db.proxy()
    split_db.account(third, 8)
    assert repository.find_replacement_proxy(failing, account_id=mover) == third


def test_scraper_never_moves_onto_sender_proxy(split_db):
    failing = split_db.proxy(health_status="down")
    sender_px = split_db.proxy()
    scraper_px = split_db.proxy()
    mover = split_db.account(failing, 0)
    split_db.account(sender_px, 8)
    for _ in range(5):
        split_db.account(scraper_px, 0)
    assert repository.find_replacement_proxy(failing, account_id=mover) == scraper_px


def test_inactive_accounts_do_not_block_the_split(split_db):
    failing = split_db.proxy(health_status="down")
    target = split_db.proxy()
    mover = split_db.account(failing, 8)
    split_db.account(target, 0, active=False)   # benched, never runs
    split_db.account(target, 8)
    assert repository.find_replacement_proxy(failing, account_id=mover) == target


def test_reassign_moves_whole_proxy_within_the_split(split_db):
    failing = split_db.proxy(health_status="down")
    a = split_db.proxy()
    b = split_db.proxy()
    movers = [split_db.account(failing, 8) for _ in range(3)]
    results = [repository.reassign_account_proxy(m) for m in movers]
    assert [r["reassigned"] for r in results] == [True, True, True]
    targets = sorted(r["new_proxy_id"] for r in results)
    assert targets.count(a) <= 2 and targets.count(b) <= 2
