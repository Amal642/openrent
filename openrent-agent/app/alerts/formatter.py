"""Formats an AlertEvent (+ optional AI explanation) into the Telegram message text."""
from __future__ import annotations

import json

_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "🔴",
    "critical": "🚨",
}


def _format_context(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return raw
    if not data:
        return None
    return ", ".join(f"{k}={v}" for k, v in data.items())


def format_alert(event, resolution_mode: str, explanation: str | None) -> str:
    emoji = _SEVERITY_EMOJI.get(event.severity, "🔴")
    lines = [f"{emoji} *{event.source.upper()}* — {event.title}"]

    if event.detail:
        lines.append(event.detail[:600])

    context_str = _format_context(event.context)
    if context_str:
        lines.append(f"_Context: {context_str}_")

    if explanation:
        lines.append("")
        lines.append("*Diagnosis:*")
        lines.append(explanation)

    lines.append("")
    if resolution_mode == "manual":
        lines.append(f"Reply `/resolve {event.source}` once this is fixed to re-arm this alert.")
    else:
        lines.append("This clears itself automatically once the check passes again.")

    return "\n".join(lines)


def format_recovery(source: str, title: str) -> str:
    return f"✅ *{source.upper()}* recovered — {title}"
