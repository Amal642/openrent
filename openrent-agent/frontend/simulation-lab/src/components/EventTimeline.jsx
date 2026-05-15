import JsonBlock from "./JsonBlock";
import Panel from "./Panel";

export default function EventTimeline({ events = [] }) {
  return (
    <Panel title="Event Timeline">
      <div className="stack">
        {events.map((event, index) => (
          <details key={`${event.timestamp}-${index}`} className="event-item">
            <summary>
              <span className="event-badge">{event.event_type}</span>
              <span>turn {event.turn_index}</span>
              <span>{event.timestamp}</span>
            </summary>
            <JsonBlock value={event.payload} />
          </details>
        ))}
        {events.length === 0 ? (
          <p className="status muted">No events available.</p>
        ) : null}
      </div>
    </Panel>
  );
}
