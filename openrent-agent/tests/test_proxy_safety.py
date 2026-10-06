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
