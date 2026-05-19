import Panel from "./Panel";

function findTimestamp(events = [], entry) {
  const match = events.find(
    (event) =>
      event.event_type === entry.source_event &&
      event.turn_index === entry.turn_index &&
      event.payload?.message === entry.message,
  );
  return match?.timestamp;
}

function speakerLabel(speaker) {
  if (speaker === "agent") {
    return "AI";
  }
  if (speaker === "actor") {
    return "Landlord";
  }
  return speaker;
}

function auditEventLabel(sourceEvent) {
  if (sourceEvent === "AGENT_INITIAL_MESSAGE_SENT") {
    return "AI opening message";
  }
  if (sourceEvent === "ACTOR_RESPONDED") {
    return "Landlord reply";
  }
  if (sourceEvent === "REPLY_GENERATED") {
    return "AI reply";
  }
  return sourceEvent;
}

export default function TranscriptViewer({
  transcript = [],
  events = [],
  auditMode = false,
}) {
  return (
    <Panel title="Conversation">
      <div className="stack">
        {transcript.map((entry, index) => {
          const timestamp = findTimestamp(events, entry);
          return (
            <article key={`${entry.turn_index}-${index}`} className="message-card">
              <div className="message-header">
                <strong>{speakerLabel(entry.speaker)}</strong>
                <span>turn {entry.turn_index}</span>
                <span>
                  {auditMode ? auditEventLabel(entry.source_event) : entry.source_event}
                </span>
                <span>{timestamp || (auditMode ? "" : "pending")}</span>
              </div>
              <p>{entry.message}</p>
            </article>
          );
        })}
        {transcript.length === 0 ? (
          <p className="status muted">No transcript available.</p>
        ) : null}
      </div>
    </Panel>
  );
}
