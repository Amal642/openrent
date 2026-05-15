import { useState } from "react";

import Panel from "./Panel";

const DEFAULT_FORM = {
  seed: 42,
  max_turns: 1,
  scenario_id: "outreach-screening-before-phone",
  actor_id: "landlord-default",
  policy_id: "production-policy-v1",
  start_mode: "agent_starts",
  initial_message_source: "fixture",
  account_id: "",
  initial_message: "",
};

export default function RunPanel({ onRun }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await onRun({
        seed: Number(form.seed),
        max_turns: Number(form.max_turns),
        scenario_id: form.scenario_id || undefined,
        actor_id: form.actor_id || undefined,
        policy_id: form.policy_id || undefined,
        start_mode: form.start_mode,
        initial_message_source:
          form.start_mode === "agent_starts"
            ? form.initial_message_source
            : undefined,
        account_id:
          form.start_mode === "agent_starts" && form.account_id
            ? Number(form.account_id)
            : undefined,
        initial_message:
          form.start_mode === "agent_starts" && form.initial_message
            ? form.initial_message
            : undefined,
      });
    } catch (runError) {
      setError(runError.message);
    } finally {
      setLoading(false);
    }
  }

  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  return (
    <Panel title="Run Panel">
      <form className="stack" onSubmit={handleSubmit}>
        <label className="field">
          <span>Seed</span>
          <input name="seed" type="number" value={form.seed} onChange={updateField} />
        </label>
        <label className="field">
          <span>Max turns</span>
          <input
            name="max_turns"
            type="number"
            min="1"
            value={form.max_turns}
            onChange={updateField}
          />
        </label>
        <label className="field">
          <span>Start mode</span>
          <select name="start_mode" value={form.start_mode} onChange={updateField}>
            <option value="actor_starts">actor_starts</option>
            <option value="agent_starts">agent_starts</option>
          </select>
        </label>
        {form.start_mode === "agent_starts" ? (
          <>
            <label className="field">
              <span>Initial message source</span>
              <select
                name="initial_message_source"
                value={form.initial_message_source}
                onChange={updateField}
              >
                <option value="fixture">fixture</option>
                <option value="account">account</option>
                <option value="manual">manual</option>
              </select>
            </label>
            {form.initial_message_source === "account" ? (
              <label className="field">
                <span>Account ID</span>
                <input
                  name="account_id"
                  type="number"
                  min="1"
                  value={form.account_id}
                  onChange={updateField}
                />
              </label>
            ) : null}
            {form.initial_message_source !== "account" ? (
              <label className="field">
                <span>Initial message override</span>
                <textarea
                  className="text-area"
                  name="initial_message"
                  value={form.initial_message}
                  onChange={updateField}
                  placeholder="Leave blank to use the default fixture message."
                />
              </label>
            ) : null}
          </>
        ) : null}
        <label className="field">
          <span>Scenario</span>
          <input name="scenario_id" value={form.scenario_id} onChange={updateField} />
        </label>
        {form.start_mode === "actor_starts" ? (
          <label className="field">
            <span>Actor</span>
            <input name="actor_id" value={form.actor_id} onChange={updateField} />
          </label>
        ) : null}
        <label className="field">
          <span>Policy</span>
          <select name="policy_id" value={form.policy_id} onChange={updateField}>
            <option value="production-policy-v1">production-policy-v1</option>
            <option value="minimal-policy-v1">minimal-policy-v1</option>
            <option value="aggressive-followup-v1">aggressive-followup-v1</option>
          </select>
        </label>
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? "Running..." : "Run Simulation"}
        </button>
        {error ? <p className="status error">{error}</p> : null}
      </form>
    </Panel>
  );
}
