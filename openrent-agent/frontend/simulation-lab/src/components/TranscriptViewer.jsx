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
  if (speaker === "agent") return "Tenant";
  if (speaker === "actor") return "Landlord";
  return speaker;
}

export default function TranscriptViewer({
  transcript = [],
  events = [],
  auditMode = false,
  bare = false,
}) {
  const thread = (
    <div className="message-thread">
      {transcript.map((entry, index) => {
        const timestamp = findTimestamp(events, entry);
        const speaker = auditMode
          ? entry.speaker === "agent" ? "AI" : "You"
          : speakerLabel(entry.speaker);
        const messageClass =
          entry.speaker === "agent"
            ? "message-card tenant-message"
            : "message-card landlord-message";

        return (
          <article key={`${entry.turn_index}-${index}`} className={messageClass}>
            <div className="message-header">
              <strong>{speaker}</strong>
              {!auditMode ? (
                <>
                  <span>turn {entry.turn_index}</span>
                  <span>{entry.source_event}</span>
                  <span>{timestamp || "pending"}</span>
                </>
              ) : null}
            </div>
            <p>{entry.message}</p>
          </article>
        );
      })}
      {transcript.length === 0 ? (
        <p className="status muted">
          {auditMode
            ? "Start a conversation to see messages here."
            : "No transcript available."}
        </p>
      ) : null}
    </div>
  );

  if (bare) {
    return <div className="transcript-bare">{thread}</div>;
  }

  return <Panel title="Conversation">{thread}</Panel>;
}
