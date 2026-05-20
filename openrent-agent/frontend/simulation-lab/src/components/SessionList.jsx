import Panel from "./Panel";

function scoreClass(passed) {
  return passed ? "status-pill pass" : "status-pill fail";
}

export default function SessionList({
  sessions,
  selectedSessionId,
  loading,
  error,
  onRefresh,
  onSelect,
  auditMode = false,
}) {
  return (
    <Panel
      title={auditMode ? "Shared Audit History" : "Session List"}
      actions={
        <button className="ghost-button" type="button" onClick={onRefresh}>
          Refresh
        </button>
      }
    >
      {loading ? <p className="status">Loading sessions...</p> : null}
      {error ? <p className="status error">{error}</p> : null}
      <div className="session-list">
        {sessions.map((session) => (
          <button
            key={session.session_id}
            type="button"
            className={
              session.session_id === selectedSessionId
                ? "session-item active"
                : "session-item"
            }
            onClick={() => onSelect(session.session_id)}
          >
            <div className="session-row">
              <strong>{session.session_id}</strong>
              <div className="session-pill-row">
                <span className="mode-pill">{session.mode || "simulation"}</span>
                <span className={scoreClass(session.passed)}>
                  {session.passed ? "pass" : "fail"}
                </span>
              </div>
            </div>
            <div className="session-meta">
              <span>{session.conversation_design_name || session.scenario_id}</span>
              <span>{auditMode ? "AI test" : session.policy_id}</span>
            </div>
            <div className="session-meta">
              <span>
                {auditMode
                  ? "AI starts"
                  : (session.start_mode || "actor_starts")}
              </span>
              <span>
                {auditMode
                  ? "landlord test"
                  : (session.initial_message_source || session.actor_id)}
              </span>
            </div>
            <div className="session-meta">
              <span>score {session.score ?? "n/a"}</span>
              <span>{session.run_duration_ms ?? "?"} ms</span>
            </div>
            <div className="session-timestamp">{session.created_at}</div>
          </button>
        ))}
        {!loading && sessions.length === 0 ? (
          <p className="status muted">
            {auditMode ? "No audit sessions found." : "No session artifacts found."}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
