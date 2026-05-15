from datetime import datetime, timezone


def build_event_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

