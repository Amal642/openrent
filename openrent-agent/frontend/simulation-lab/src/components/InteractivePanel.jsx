import { useState } from "react";

import Panel from "./Panel";

const DEFAULT_FORM = {
  scenario_id: "outreach-screening-before-phone",
  policy_id: "production-policy-v1",
  start_mode: "agent_starts",
  initial_message_source: "fixture",
  account_id: "",
  initial_message: "",
};

export default function InteractivePanel({
  activeSession,
  onStart,
  onSend,
  auditMode = false,
}) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [message, setMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function handleStart(event) {
    event.preventDefault();
    setStarting(true);
    setError("");
    try {
      await onStart({
        scenario_id: form.scenario_id || undefined,
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
    } catch (startError) {
      setError(startError.message);
    } finally {
      setStarting(false);
    }
  }

  async function handleSend(event) {
    event.preventDefault();
    if (!activeSession || !message.trim()) {
      return;
    }
    setSending(true);
    setError("");
    try {
      await onSend(activeSession.session_id, message.trim());
      setMessage("");
    } catch (sendError) {
      setError(sendError.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <Panel title={auditMode ? "Landlord Test" : "Interactive Session"}>
      <div className="stack">
        {auditMode ? (
          <form className="stack" onSubmit={handleStart}>
            <div className="status">
              Start a shared audit session. The AI sends the opening tenant message first,
              then respond as the landlord to test how the model handles phone-number capture.
            </div>
            <button className="primary-button" type="submit" disabled={starting}>
              {starting ? "Starting..." : "Start Audit Session"}
            </button>
          </form>
        ) : (
          <form className="stack" onSubmit={handleStart}>
            <label className="field">
              <span>Start mode</span>
              <select name="start_mode" value={form.start_mode} onChange={updateField}>
                <option value="actor_starts">actor_starts</option>
                <option value="agent_starts">agent_starts</option>
              </select>
            </label>
            <label className="field">
              <span>Scenario</span>
              <input name="scenario_id" value={form.scenario_id} onChange={updateField} />
            </label>
            <label className="field">
              <span>Policy</span>
              <select name="policy_id" value={form.policy_id} onChange={updateField}>
                <option value="production-policy-v1">production-policy-v1</option>
                <option value="minimal-policy-v1">minimal-policy-v1</option>
                <option value="aggressive-followup-v1">aggressive-followup-v1</option>
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
            <button className="primary-button" type="submit" disabled={starting}>
              {starting ? "Starting..." : "Start Interactive Session"}
            </button>
          </form>
        )}

        <form className="stack" onSubmit={handleSend}>
          <label className="field">
            <span>{auditMode ? "Landlord message" : "Actor message"}</span>
            <textarea
              className="text-area"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={
                activeSession?.start_mode === "agent_starts"
                  ? "Type the landlord reply to the AI's opening message here."
                  : "Type the landlord or persona message here."
              }
              disabled={!activeSession || sending}
            />
          </label>
          <button
            className="primary-button"
            type="submit"
            disabled={!activeSession || sending || !message.trim()}
          >
            {sending ? "Sending..." : "Send Message"}
          </button>
        </form>

        <div className="status">
          {activeSession
            ? auditMode
              ? `Active audit session: ${activeSession.session_id}`
              : `Active session: ${activeSession.session_id} (${activeSession.start_mode})`
            : "Start an interactive session to respond as the landlord."}
        </div>
        {error ? <p className="status error">{error}</p> : null}
      </div>
    </Panel>
  );
}
