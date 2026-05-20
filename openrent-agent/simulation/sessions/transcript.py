from dataclasses import dataclass


@dataclass
class ConversationTurn:
    speaker: str
    message: str
    turn_index: int
    source_event: str


def project_transcript(events) -> list[ConversationTurn]:
    transcript = []
    for event in events:
        if event.event_type == "ACTOR_RESPONDED":
            transcript.append(
                ConversationTurn(
                    speaker="actor",
                    message=event.payload["message"],
                    turn_index=event.turn_index,
                    source_event=event.event_type,
                )
            )
        elif (
            event.event_type == "AGENT_INITIAL_MESSAGE_SENT"
            and event.payload.get("message")
        ):
            transcript.append(
                ConversationTurn(
                    speaker="agent",
                    message=event.payload["message"],
                    turn_index=event.turn_index,
                    source_event=event.event_type,
                )
            )
        elif (
            event.event_type == "REPLY_GENERATED"
            and event.payload.get("reply_text")
        ):
            transcript.append(
                ConversationTurn(
                    speaker="agent",
                    message=event.payload["reply_text"],
                    turn_index=event.turn_index,
                    source_event=event.event_type,
                )
            )
    return transcript
