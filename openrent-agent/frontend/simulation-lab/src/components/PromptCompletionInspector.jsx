import Panel from "./Panel";

function findReplyGeneratedEvent(events = []) {
  return [...events]
    .reverse()
    .find((event) => event.event_type === "REPLY_GENERATED");
}

export default function PromptCompletionInspector({ session, observability }) {
  if (!session) {
    return (
      <Panel title="Prompt Completion Inspector">
        <p className="status muted">No prompt/completion loaded.</p>
      </Panel>
    );
  }

  const eventPayload = findReplyGeneratedEvent(session.events)?.payload || {};
  const lastAgent = session.runtime_context?.last_agent_response || {};
  const rawPrompt = lastAgent.raw_prompt || eventPayload.raw_prompt;
  const rawCompletion = lastAgent.raw_completion || eventPayload.raw_completion;

  return (
    <Panel title="Prompt Completion Inspector">
      <div className="metric-grid">
        <div className="metric-card">
          <span>Model</span>
          <strong>{lastAgent.model || eventPayload.model || "n/a"}</strong>
        </div>
        <div className="metric-card">
          <span>Temperature</span>
          <strong>{lastAgent.temperature ?? eventPayload.temperature ?? "n/a"}</strong>
        </div>
        <div className="metric-card">
          <span>Tokens</span>
          <strong>{lastAgent.total_tokens ?? observability?.total_tokens ?? 0}</strong>
        </div>
        <div className="metric-card">
          <span>Latency ms</span>
          <strong>{lastAgent.latency_ms ?? eventPayload.latency_ms ?? "n/a"}</strong>
        </div>
      </div>
      <div className="stack">
        <div>
          <h3>Raw Prompt</h3>
          <pre className="code-block">{rawPrompt || "No raw prompt in artifact."}</pre>
        </div>
        <div>
          <h3>Raw Completion</h3>
          <pre className="code-block">
            {rawCompletion || "No raw completion in artifact."}
          </pre>
        </div>
      </div>
    </Panel>
  );
}
