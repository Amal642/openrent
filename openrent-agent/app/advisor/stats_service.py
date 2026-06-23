"""
Queries the platform database and formats answers to statistics questions.
No LLM calls used here — data is read directly and formatted as plain text.
"""

import re
from datetime import datetime

from app.db.repository import (
    count_new_outreach_on_day,
    get_capacity_stats,
    get_dashboard_accounts,
    get_dashboard_leads,
    get_proxies,
)


def _account_snapshot() -> dict:
    accounts = get_dashboard_accounts()
    total = len(accounts)
    active = sum(1 for a in accounts if a.get("active"))
    disabled = sum(1 for a in accounts if not a.get("active"))
    perm_failed = sum(1 for a in accounts if a.get("permanently_failed"))
    running = sum(1 for a in accounts if (a.get("worker_status") or "") == "running")
    messages_today = sum(a.get("messages_sent_today", 0) for a in accounts)
    daily_capacity = sum(
        a.get("daily_message_limit", 0) for a in accounts if a.get("active")
    )
    return {
        "total": total,
        "active": active,
        "disabled": disabled,
        "permanently_failed": perm_failed,
        "currently_running": running,
        "messages_sent_today": messages_today,
        "daily_capacity": daily_capacity,
    }


def _proxy_snapshot() -> dict:
    cap = get_capacity_stats()
    return {
        "total": cap.get("total_proxies", 0),
        "healthy": cap.get("healthy_proxies", 0),
        "failed": cap.get("failed_proxies", 0),
        "degraded": max(
            0,
            cap.get("total_proxies", 0)
            - cap.get("healthy_proxies", 0)
            - cap.get("failed_proxies", 0),
        ),
    }


def _lead_snapshot() -> dict:
    leads = get_dashboard_leads()
    total = len(leads)
    with_phone = sum(1 for l in leads if l.get("phone_number"))
    replied = sum(1 for l in leads if l.get("last_processed_message"))
    active = sum(
        1
        for l in leads
        if l.get("status") in ("INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED")
    )
    failed = sum(1 for l in leads if l.get("status") == "AI_FAILED")
    reply_rate = round((replied / max(total, 1)) * 100)
    outreach_today = count_new_outreach_on_day()
    return {
        "total_leads": total,
        "active_conversations": active,
        "phone_numbers_collected": with_phone,
        "landlords_replied": replied,
        "reply_rate_pct": reply_rate,
        "ai_failed": failed,
        "new_outreach_today": outreach_today,
    }


# ---------------------------------------------------------------------------
# Keyword groups used to select which part of the snapshot to highlight
# ---------------------------------------------------------------------------

_ACCOUNT_KEYWORDS = re.compile(
    r"\b(accounts?|workers?|active|disabled|running|capacity|daily limit)\b", re.I
)
_PROXY_KEYWORDS = re.compile(
    r"\b(prox(y|ies)|connection|tunnel|degraded|down|healthy)\b", re.I
)
_MESSAGE_KEYWORDS = re.compile(
    r"\b(messages?|sent|outreach|today|listings? found|contacted)\b", re.I
)
_LEAD_KEYWORDS = re.compile(
    r"\b(leads?|conversations?|phones?|numbers?|collected|reply rate|replies?|failed)\b",
    re.I,
)


def answer_stats_question(question: str) -> str:
    a = _account_snapshot()
    p = _proxy_snapshot()
    l = _lead_snapshot()

    wants_accounts = bool(_ACCOUNT_KEYWORDS.search(question))
    wants_proxies = bool(_PROXY_KEYWORDS.search(question))
    wants_messages = bool(_MESSAGE_KEYWORDS.search(question))
    wants_leads = bool(_LEAD_KEYWORDS.search(question))

    # If nothing specific matched, return a full summary
    if not any([wants_accounts, wants_proxies, wants_messages, wants_leads]):
        wants_accounts = wants_proxies = wants_messages = wants_leads = True

    parts = []

    if wants_accounts:
        parts.append(
            f"**Accounts**\n"
            f"• Total: {a['total']}\n"
            f"• Active: {a['active']}\n"
            f"• Disabled: {a['disabled']}\n"
            f"• Currently running: {a['currently_running']}\n"
            f"• Permanently failed: {a['permanently_failed']}\n"
            f"• Messages sent today: {a['messages_sent_today']}\n"
            f"• Daily message capacity: {a['daily_capacity']} messages"
        )

    if wants_proxies:
        parts.append(
            f"**Connection Services (Proxies)**\n"
            f"• Total: {p['total']}\n"
            f"• Healthy: {p['healthy']}\n"
            f"• Degraded: {p['degraded']}\n"
            f"• Down / failed: {p['failed']}"
        )

    if wants_messages:
        parts.append(
            f"**Messages & Outreach**\n"
            f"• New landlords contacted today: {l['new_outreach_today']}\n"
            f"• Active conversations: {l['active_conversations']}"
        )

    if wants_leads:
        parts.append(
            f"**Leads & Results**\n"
            f"• Total leads: {l['total_leads']}\n"
            f"• Landlords who replied: {l['landlords_replied']}\n"
            f"• Reply rate: {l['reply_rate_pct']}%\n"
            f"• Phone numbers collected: {l['phone_numbers_collected']}\n"
            f"• Failed conversations: {l['ai_failed']}"
        )

    return "\n\n".join(parts) if parts else "No data available at the moment."


def all_stats_for_prompt() -> str:
    """Compact stats string for inclusion in an OpenAI recommendation prompt."""
    a = _account_snapshot()
    p = _proxy_snapshot()
    l = _lead_snapshot()
    return (
        f"Accounts: {a['active']} active / {a['total']} total, "
        f"{a['messages_sent_today']} messages sent today, "
        f"{a['daily_capacity']} daily capacity\n"
        f"Connection services: {p['healthy']} healthy, {p['degraded']} degraded, {p['failed']} down\n"
        f"Leads: {l['total_leads']} total, "
        f"{l['landlords_replied']} replies ({l['reply_rate_pct']}% rate), "
        f"{l['phone_numbers_collected']} phones collected, "
        f"{l['new_outreach_today']} new contacts today"
    )
