import Panel from "./Panel";

const STATE_LABELS = {
  initial_interest: "Initial interest",
  screening: "Screening",
  viewing_negotiation: "Viewing negotiation",
  viewing_confirmed: "Viewing confirmed",
  coordination: "Coordination",
  phone_captured: "Phone captured",
  stalled: "Stalled",
};

const SIGNAL_LABELS = {
  viewing_requested: "Viewing requested",
  screening_questions_asked: "Screening questions asked",
  screening_answered: "Screening answered",
  viewing_time_offered: "Viewing time offered",
  viewing_confirmed: "Viewing confirmed",
  phone_requested: "Phone requested",
  phone_requested_too_early: "Phone requested too early",
  phone_captured: "Phone captured",
  landlord_refused_phone: "Landlord refused phone",
  ai_pushed_after_refusal: "AI pushed after refusal",
  conversation_stalled: "Conversation stalled",
};

export function formatStateLabel(state) {
  return STATE_LABELS[state] || "Unknown";
}

export function activeSignalLabels(conversationState) {
  const signals = conversationState?.signals || {};
  return Object.entries(signals)
    .filter(([, value]) => Boolean(value))
    .map(([key]) => SIGNAL_LABELS[key] || key.replaceAll("_", " "));
}

export default function ConversationStatePanel({ conversationState }) {
  if (!conversationState) {
    return (
      <Panel title="Conversation State">
        <p className="status muted">No conversation state loaded.</p>
      </Panel>
    );
  }

  const signalLabels = activeSignalLabels(conversationState);

  return (
    <Panel title="Conversation State">
      <div className="metric-grid compact">
        <div className="metric-card">
          <span>State</span>
          <strong>{formatStateLabel(conversationState.current_state)}</strong>
        </div>
      </div>
      <div className="stack">
        <div>
          <h3>Signals</h3>
          {signalLabels.length ? (
            <div className="signal-list">
              {signalLabels.map((label) => (
                <span key={label} className="signal-pill">
                  {label}
                </span>
              ))}
            </div>
          ) : (
            <p className="status muted">No key signals yet.</p>
          )}
        </div>
        <div>
          <h3>Rationale</h3>
          <div className="mini-transcript">
            {(conversationState.rationale || []).map((item) => (
              <p key={item}>{item}</p>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
