import { useState } from "react";

import Panel from "./Panel";
import { activeSignalLabels, formatStateLabel } from "./ConversationStatePanel";

const DEFAULT_SELECTED = ["viewing_first_v1", "confirmation_close_v1"];
const DEFAULT_SCENARIO_ID = "normal_viewing_offer";

function speakerLabel(speaker) {
  if (speaker === "agent") {
    return "Tenant";
  }
  if (speaker === "actor") {
    return "Landlord";
  }
  return speaker;
}

export default function CompareDesignsPanel({
  conversationDesigns = [],
  conversationScenarios = [],
  onCompare,
}) {
  const [selectedDesignIds, setSelectedDesignIds] = useState(DEFAULT_SELECTED);
  const [selectedScenarioId, setSelectedScenarioId] = useState(DEFAULT_SCENARIO_ID);
  const [landlordMessage, setLandlordMessage] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const designOptions = conversationDesigns.length
    ? conversationDesigns
    : [
        { id: "viewing_first_v1", name: "Viewing first" },
        { id: "confirmation_close_v1", name: "Confirmation close" },
      ];
  const scenarioOptions = conversationScenarios.length
    ? conversationScenarios
    : [
        {
          scenario_id: DEFAULT_SCENARIO_ID,
          name: "Normal viewing offer",
          landlord_initial_message:
            "Hi Mary, yes viewing is possible. Are you free tomorrow evening?",
        },
      ];
  const selectedScenario = scenarioOptions.find(
    (scenario) => scenario.scenario_id === selectedScenarioId,
  );
  const testedMessage =
    landlordMessage.trim() ||
    selectedScenario?.landlord_initial_message ||
    "No landlord message selected.";

  function toggleDesign(designId) {
    setSelectedDesignIds((current) => {
      if (current.includes(designId)) {
        return current.filter((id) => id !== designId);
      }
      if (current.length >= 4) {
        return current;
      }
      return [...current, designId];
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = await onCompare({
        conversation_design_ids: selectedDesignIds,
        scenario_id: selectedScenarioId || null,
        initial_landlord_message: landlordMessage.trim() || null,
        max_turns: 1,
      });
      setResults(payload);
    } catch (compareError) {
      setError(compareError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Panel title="Compare Message Styles">
      <form className="stack" onSubmit={handleSubmit}>
        <div className="design-check-grid">
          {designOptions.map((design) => (
            <label key={design.id} className="check-row design-option">
              <input
                type="checkbox"
                checked={selectedDesignIds.includes(design.id)}
                onChange={() => toggleDesign(design.id)}
              />
              <span>
                <strong>{design.name}</strong>
                {design.description ? <small>{design.description}</small> : null}
              </span>
            </label>
          ))}
        </div>
        <label className="field">
          <span>Landlord situation</span>
          <select
            value={selectedScenarioId}
            onChange={(event) => setSelectedScenarioId(event.target.value)}
          >
            {scenarioOptions.map((scenario) => (
              <option key={scenario.scenario_id} value={scenario.scenario_id}>
                {scenario.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Or write your own landlord message</span>
          <textarea
            className="text-area"
            value={landlordMessage}
            onChange={(event) => setLandlordMessage(event.target.value)}
            placeholder={selectedScenario?.landlord_initial_message}
          />
        </label>
        <div className="status muted">
          <strong>Message being tested:</strong> {testedMessage}
        </div>
        <button
          className="primary-button"
          type="submit"
          disabled={loading || selectedDesignIds.length < 1 || selectedDesignIds.length > 4}
        >
          {loading ? "Comparing..." : "Compare Styles"}
        </button>
        {error ? <p className="status error">{error}</p> : null}
      </form>

      {results?.results?.length ? (
        <div className="compare-grid">
          {results.results.map((result) => (
            <article key={result.design_id} className="compare-card">
              <div className="session-row">
                <strong>{result.design_name}</strong>
                <span className={result.passed ? "status-pill pass" : "status-pill fail"}>
                  {result.score}
                </span>
              </div>
              <p className="session-meta">
                Scenario: {result.scenario_name || results.scenario_name || "Custom message"}
              </p>
              <div className="metric-grid compact">
                <div className="metric-card">
                  <span>Phone</span>
                  <strong>{result.phone_captured ? "yes" : "no"}</strong>
                </div>
                <div className="metric-card">
                  <span>Viewing</span>
                  <strong>{result.viewing_progressed ? "progressed" : "no progress"}</strong>
                </div>
                <div className="metric-card">
                  <span>State</span>
                  <strong>{formatStateLabel(result.conversation_state?.current_state)}</strong>
                </div>
              </div>
              <div className="stack">
                <div>
                  <h3>Signals</h3>
                  <div className="signal-list">
                    {activeSignalLabels(result.conversation_state).map((label) => (
                      <span key={`${result.design_id}-${label}`} className="signal-pill">
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <h3>Failures</h3>
                  <p className="status muted">
                    {result.failure_reasons?.length
                      ? result.failure_reasons.join(", ")
                      : "No issues detected"}
                  </p>
                </div>
                <div>
                  <h3>Transcript</h3>
                  <div className="mini-transcript">
                    {result.transcript.map((turn, index) => (
                      <p key={`${result.design_id}-${index}`}>
                        <strong>{speakerLabel(turn.speaker)}:</strong> {turn.message}
                      </p>
                    ))}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
