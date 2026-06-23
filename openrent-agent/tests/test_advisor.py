from datetime import datetime, timedelta

from app.advisor import stats_service
from app.advisor.handler import handle_chat


def test_identity_question_returns_info_response():
    result = handle_chat("Who are you?")

    assert result["type"] == "info"
    assert "Land Royal Operations Advisor" in result["response"]


def test_out_of_scope_question_is_refused_without_llm():
    result = handle_chat("Tell me a joke")

    assert result["type"] == "out_of_scope"
    assert "OpenRent operations" in result["response"]


def test_troubleshooting_question_uses_guide():
    result = handle_chat("Why are messages not sending?")

    assert result["type"] == "troubleshooting"
    assert "Messages Not Sending" in result["response"]


def test_stats_phone_count_separates_today_from_total(monkeypatch):
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    monkeypatch.setattr(stats_service, "get_dashboard_accounts", lambda: [])
    monkeypatch.setattr(
        stats_service,
        "get_capacity_stats",
        lambda: {
            "total_proxies": 0,
            "healthy_proxies": 0,
            "failed_proxies": 0,
        },
    )
    monkeypatch.setattr(stats_service, "count_new_outreach_on_day", lambda: 3)
    monkeypatch.setattr(
        stats_service,
        "get_dashboard_leads",
        lambda: [
            {
                "phone_number": "07111111111",
                "phone_found_at": now,
                "last_processed_message": "Yes",
                "status": "PHONE_ACQUIRED",
            },
            {
                "phone_number": "07222222222",
                "phone_found_at": yesterday,
                "last_processed_message": "",
                "status": "PHONE_ACQUIRED",
            },
            {
                "phone_number": "",
                "phone_found_at": now,
                "last_processed_message": "",
                "status": "INITIAL_MESSAGE_SENT",
            },
        ],
    )

    response = stats_service.answer_stats_question(
        "How many phone numbers were collected today?"
    )

    assert "Phone numbers collected today: 1" in response
    assert "Phone numbers collected total: 2" in response
    assert "New landlords contacted today: 3" in response


def test_stats_daily_capacity_accepts_backend_daily_limit(monkeypatch):
    monkeypatch.setattr(
        stats_service,
        "get_dashboard_accounts",
        lambda: [
            {
                "active": True,
                "daily_limit": 8,
                "messages_sent_today": 2,
                "worker_status": "idle",
            },
            {
                "active": False,
                "daily_limit": 8,
                "messages_sent_today": 1,
                "worker_status": "idle",
            },
        ],
    )
    monkeypatch.setattr(
        stats_service,
        "get_capacity_stats",
        lambda: {
            "total_proxies": 0,
            "healthy_proxies": 0,
            "failed_proxies": 0,
        },
    )
    monkeypatch.setattr(stats_service, "count_new_outreach_on_day", lambda: 0)
    monkeypatch.setattr(stats_service, "get_dashboard_leads", lambda: [])

    response = stats_service.answer_stats_question("How many active accounts?")

    assert "Active: 1" in response
    assert "Messages sent today: 3" in response
    assert "Daily message capacity: 8 messages" in response
