def format_replay(events, transcript, evaluation) -> str:
    lines = ["Simulation Replay", "================="]
    lines.append("")
    lines.append("Transcript")
    lines.append("----------")
    for turn in transcript:
        lines.append(f"{turn.speaker.upper()}: {turn.message}")
    lines.append("")
    lines.append("Evaluation")
    lines.append("----------")
    lines.append(f"score={evaluation.score}")
    lines.append(f"passed={evaluation.passed}")
    if evaluation.failure_types:
        lines.append("failures=" + ", ".join(evaluation.failure_types))
    lines.append("")
    lines.append("Events")
    lines.append("------")
    for event in events:
        lines.append(f"{event.timestamp} [{event.event_type}] {event.payload}")
    return "\n".join(lines)

