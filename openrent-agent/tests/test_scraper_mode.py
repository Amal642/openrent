"""Scraper mode (2026-10-06): accounts restricted on OpenRent get daily_limit 0.
They keep answering old threads and keep SEARCHING their areas (longer
cooldown), but never send; senders overflow-claim what they find."""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("rq")  # the worker module needs rq (installed on prod)

from app.workers import account_worker as aw  # noqa: E402


def test_is_scraper_account():
    assert aw.is_scraper_account(SimpleNamespace(daily_limit=0)) is True
    assert aw.is_scraper_account(SimpleNamespace(daily_limit=8)) is False
    # NULL limit is the model default (8), never a scraper.
    assert aw.is_scraper_account(SimpleNamespace(daily_limit=None)) is False


@pytest.fixture()
def run(monkeypatch):
    calls = {"discovery": [], "outreach": 0, "replies": 0, "reminders": 0}

    async def fake_launch(account):
        return None, None, None, "page"

    async def fake_login(page, context, account):
        return None

    async def fake_replies(account, page, worker_id=None):
        calls["replies"] += 1

    async def fake_reminders(account, page, worker_id=None):
        calls["reminders"] += 1

    async def fake_outreach(account, page, worker_id=None):
        calls["outreach"] += 1

    async def fake_scrape(account, page, new_limit=None):
        calls["discovery"].append("scraped")

    def fake_should_scrape(account_id, cooldown_hours=2):
        calls["discovery"].append(cooldown_hours)
        return True

    monkeypatch.setattr(aw, "is_operating_hours", lambda: True)
    monkeypatch.setattr(aw, "_proxy_url_for_account", lambda a: "http://u:p@isp.decodo.com:10001")
    monkeypatch.setattr(aw, "_proxy_check_is_fresh", lambda a: True)
    monkeypatch.setattr(aw, "launch_browser", fake_launch)
    monkeypatch.setattr(aw, "login", fake_login)
    monkeypatch.setattr(aw, "process_account_replies", fake_replies)
    monkeypatch.setattr(aw, "process_account_viewing_reminders", fake_reminders)
    monkeypatch.setattr(aw, "process_account_listings", fake_outreach)
    monkeypatch.setattr(aw, "scrape_account_listings", fake_scrape)
    monkeypatch.setattr(aw, "should_scrape_now", fake_should_scrape)
    monkeypatch.setattr(aw, "count_available_inventory", lambda account_id: 0)
    monkeypatch.setattr(aw, "count_discovered_today", lambda account_id: 0)
    monkeypatch.setattr(aw, "account_stop_requested", lambda account_id: False)
    monkeypatch.setattr(aw, "update_account_worker_state", lambda *a, **k: None)
    monkeypatch.setattr(aw, "set_account_cooldown", lambda account_id: None)
    monkeypatch.setattr(aw.settings, "DISCOVERY_COOLDOWN_HOURS", 4)
    monkeypatch.setattr(aw.settings, "SCRAPER_DISCOVERY_COOLDOWN_HOURS", 10)

    def _run(daily_limit, can_send=True, proxy_url="http://u:p@isp.decodo.com:10001"):
        monkeypatch.setattr(aw, "can_send_message", lambda account_id: can_send)
        monkeypatch.setattr(aw, "_proxy_url_for_account", lambda a: proxy_url)
        account = SimpleNamespace(id=99, email="x@y", daily_limit=daily_limit, proxy=None)
        asyncio.run(aw.run_account_worker(account))
        return calls

    return _run


def test_scraper_searches_with_long_cooldown_and_never_sends(run):
    calls = run(daily_limit=0, can_send=False)
    assert calls["replies"] == 1 and calls["reminders"] == 1   # old threads still handled
    assert calls["discovery"] == [10, "scraped"]
    assert calls["outreach"] == 0


def test_sender_at_limit_neither_searches_nor_sends(run):
    calls = run(daily_limit=8, can_send=False)
    assert calls["replies"] == 1
    assert calls["discovery"] == []
    assert calls["outreach"] == 0


def test_normal_sender_searches_with_normal_cooldown_then_sends(run):
    calls = run(daily_limit=8, can_send=True)
    assert calls["discovery"] == [4, "scraped"]
    assert calls["outreach"] == 1


def test_account_without_usable_proxy_never_runs(run):
    # Never browse OpenRent from the server's own IP (2026-10-06 failover bug).
    calls = run(daily_limit=8, proxy_url=None)
    assert calls["replies"] == 0 and calls["discovery"] == [] and calls["outreach"] == 0
