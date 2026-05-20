def summarize_timeline(events) -> list[dict]:
    return [
        {
            "event_type": event.event_type,
            "turn_index": event.turn_index,
            "timestamp": event.timestamp,
        }
        for event in events
    ]

