import asyncio
import json
from datetime import datetime, timedelta

from app.alerts import health_checks


class DummyManager:
    def clear_signature_if_active(self, signature):
        return False

    async def send_recovery_notice(self, source, title):
        raise AssertionError("recovery notice was not expected")


def _heartbeat(status, *, seconds_ago=0):
    return json.dumps(
        {
            "status": status,
            "at": (datetime.utcnow() - timedelta(seconds=seconds_ago)).isoformat(),
        }
    )


def test_whatsapp_needs_scan_reports_alert(monkeypatch):
    reported = []

    monkeypatch.setattr(
        health_checks,
        "get_app_setting",
        lambda key: _heartbeat("needs_scan"),
    )
    monkeypatch.setattr(
        health_checks.events,
        "report_error",
        lambda *args, **kwargs: reported.append(args),
    )

    asyncio.run(health_checks._check_whatsapp(DummyManager()))

    assert len(reported) == 1
    assert reported[0][:2] == ("whatsapp", "WhatsApp session needs attention")


def test_whatsapp_fresh_transient_state_does_not_report(monkeypatch):
    reported = []

    monkeypatch.setattr(
        health_checks,
        "get_app_setting",
        lambda key: _heartbeat("reconnecting"),
    )
    monkeypatch.setattr(
        health_checks.events,
        "report_error",
        lambda *args, **kwargs: reported.append(args),
    )

    asyncio.run(health_checks._check_whatsapp(DummyManager()))

    assert reported == []


def test_whatsapp_stale_transient_state_reports_alert(monkeypatch):
    reported = []

    monkeypatch.setattr(
        health_checks,
        "get_app_setting",
        lambda key: _heartbeat(
            "reconnecting",
            seconds_ago=health_checks.WHATSAPP_HEARTBEAT_STALE_SECONDS + 1,
        ),
    )
    monkeypatch.setattr(
        health_checks.events,
        "report_error",
        lambda *args, **kwargs: reported.append(args),
    )

    asyncio.run(health_checks._check_whatsapp(DummyManager()))

    assert len(reported) == 1
