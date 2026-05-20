import JsonBlock from "./JsonBlock";
import Panel from "./Panel";

export default function RuntimeContextPanel({ runtimeContext }) {
  if (!runtimeContext) {
    return (
      <Panel title="Runtime Context">
        <p className="status muted">No runtime context loaded.</p>
      </Panel>
    );
  }

  return (
    <Panel title="Runtime Context">
      <div className="metric-grid">
        <div className="metric-card">
          <span>Current turn</span>
          <strong>{runtimeContext.current_turn}</strong>
        </div>
        <div className="metric-card">
          <span>Trust score</span>
          <strong>{runtimeContext.trust_score}</strong>
        </div>
      </div>
      <div className="stack">
        <div>
          <h3>Extracted Entities</h3>
          <JsonBlock value={runtimeContext.extracted_entities} />
        </div>
        <div>
          <h3>Flags</h3>
          <JsonBlock value={runtimeContext.flags} />
        </div>
        <div>
          <h3>Metrics</h3>
          <JsonBlock value={runtimeContext.metrics} />
        </div>
        <div>
          <h3>Goal Progress</h3>
          <JsonBlock value={runtimeContext.goal_progress} />
        </div>
        <div>
          <h3>Last Agent Response</h3>
          <JsonBlock value={runtimeContext.last_agent_response} />
        </div>
        <div>
          <h3>Last Actor Response</h3>
          <JsonBlock value={runtimeContext.last_actor_response} />
        </div>
      </div>
    </Panel>
  );
}
