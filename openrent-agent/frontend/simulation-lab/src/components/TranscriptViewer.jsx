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

export default function TranscriptViewer({ transcript = [], events = [] }) {
  return (
    <Panel title="Transcript Viewer">
      <div className="stack">
        {transcript.map((entry, index) => {
          const timestamp = findTimestamp(events, entry);
          return (
            <article key={`${entry.turn_index}-${index}`} className="message-card">
              <div className="message-header">
                <strong>{entry.speaker}</strong>
                <span>turn {entry.turn_index}</span>
                <span>{entry.source_event}</span>
                <span>{timestamp || "pending"}</span>
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
