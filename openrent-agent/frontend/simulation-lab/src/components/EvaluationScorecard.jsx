import JsonBlock from "./JsonBlock";
import Panel from "./Panel";

export default function EvaluationScorecard({
  evaluation,
  failureTypes,
  auditMode = false,
  phoneCaptured = false,
}) {
  if (!evaluation) {
    return (
      <Panel title="Evaluation Scorecard">
        <p className="status muted">No evaluation loaded.</p>
      </Panel>
    );
  }

  return (
    <Panel title="Evaluation Scorecard">
      <div className="metric-grid">
        <div className="metric-card">
          <span>Score</span>
          <strong>{evaluation.score}</strong>
        </div>
        <div className="metric-card">
          <span>Passed</span>
          <strong>{String(evaluation.passed)}</strong>
        </div>
        <div className="metric-card">
          <span>Phone Captured</span>
          <strong>{phoneCaptured ? "yes" : "no"}</strong>
        </div>
        {!auditMode ? (
          <>
            <div className="metric-card">
              <span>Evaluator</span>
              <strong>{evaluation.evaluator_id}</strong>
            </div>
            <div className="metric-card">
              <span>Eval ms</span>
              <strong>{evaluation.evaluation_timing_ms}</strong>
            </div>
          </>
        ) : null}
      </div>
      <div className="stack">
        <div>
          <h3>Failure Types</h3>
          <JsonBlock value={failureTypes} empty="[]" />
        </div>
        {!auditMode ? (
          <>
            <div>
              <h3>Dimension Scores</h3>
              <JsonBlock value={evaluation.dimension_scores} />
            </div>
            <div>
              <h3>Rationale</h3>
              <pre className="code-block">{evaluation.rationale}</pre>
            </div>
          </>
        ) : null}
      </div>
    </Panel>
  );
}
