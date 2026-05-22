import { useState } from "react";

import Panel from "./Panel";

const DEFAULT_FORM = {
  scenario_id: "outreach-screening-before-phone",
  policy_id: "production-policy-v1",
  start_mode: "agent_starts",
  initial_message_source: "fixture",
  conversation_design_id: "viewing_first_v1",
  account_id: "",
  initial_message: "",
};

export default function InteractivePanel({
  activeSession,
  onStart,
  onSend,
  auditMode = false,
  conversationDesigns = [],
  interactiveScenarios = [],
}) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [message, setMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [pickingNew, setPickingNew] = useState(false);

  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function startSession() {
    setStarting(true);
    setError("");
    try {
      await onStart({
        scenario_id: form.scenario_id || undefined,
        policy_id: form.policy_id || undefined,
        start_mode: form.start_mode,
        initial_message_source:
          form.start_mode === "agent_starts" ? form.initial_message_source : undefined,
        account_id:
          form.start_mode === "agent_starts" && form.account_id
            ? Number(form.account_id)
            : undefined,
        initial_message:
          form.start_mode === "agent_starts" && form.initial_message
            ? form.initial_message
            : undefined,
        conversation_design_id: form.conversation_design_id,
      });
      setPickingNew(false);
    } catch (startError) {
      setError(startError.message);
    } finally {
      setStarting(false);
    }
  }

  async function handleStart(event) {
    event.preventDefault();
    await startSession();
  }

  async function handleSend(event) {
    event.preventDefault();
    if (!activeSession || !message.trim()) return;
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

  if (auditMode) {
    const designs = conversationDesigns.length
      ? conversationDesigns
      : [{ id: "viewing_first_v1", name: "Viewing first" }];
    const selectedDesignName =
      designs.find((d) => d.id === form.conversation_design_id)?.name || "Viewing first";

    return (
      <div className="audit-chat-controls">
        {!activeSession || pickingNew ? (
          <form className="chat-start-form" onSubmit={handleStart}>
            <p className="chat-hint">
              The AI sends the first message. Reply as the landlord to see how the
              conversation moves toward a viewing.
            </p>
            {interactiveScenarios.length > 0 ? (
              <div className="property-picker">
                {interactiveScenarios.map((s) => {
                  const p = s.property || {};
                  const label = p.title || s.title;
                  const meta = [
                    p.bedrooms ? `${p.bedrooms}-bed` : null,
                    p.rent_pcm ? `£${p.rent_pcm.toLocaleString()}/mo` : null,
                    p.furnished !== undefined ? (p.furnished ? "furnished" : "unfurnished") : null,
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  const isActive = form.scenario_id === s.scenario_id;
                  return (
                    <button
                      key={s.scenario_id}
                      type="button"
                      className={isActive ? "property-option active" : "property-option"}
                      onClick={() =>
                        setForm((f) => ({ ...f, scenario_id: s.scenario_id }))
                      }
                    >
                      <span className="property-option-title">{label}</span>
                      {meta ? <span className="property-option-meta">{meta}</span> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
            <div className="chat-start-actions">
              <select
                className="design-picker-select"
                name="conversation_design_id"
                value={form.conversation_design_id}
                onChange={updateField}
              >
                {designs.map((design) => (
                  <option key={design.id} value={design.id}>
                    {design.name}
                  </option>
                ))}
              </select>
              {pickingNew && activeSession ? (
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => setPickingNew(false)}
                >
                  Cancel
                </button>
              ) : null}
              <button className="primary-button" type="submit" disabled={starting}>
                {starting ? "Starting…" : "Start →"}
              </button>
            </div>
          </form>
        ) : (
          <form className="chat-reply-form" onSubmit={handleSend}>
            <div className="chat-reply-row">
              <textarea
                className="chat-reply-input"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Reply as the landlord…"
                disabled={sending}
              />
              <div className="chat-reply-actions">
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => setPickingNew(true)}
                >
                  New conversation
                </button>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={sending || !message.trim()}
                >
                  {sending ? "Sending…" : "Send →"}
                </button>
              </div>
            </div>
          </form>
        )}

        {error ? (
          <p className="status error" style={{ margin: "0 18px 14px" }}>
            {error}
          </p>
        ) : null}

        {activeSession ? (
          <div className="chat-controls-footer">
            Active test · {selectedDesignName}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <Panel title="Interactive Session">
      <div className="stack">
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
          <label className="field">
            <span>Conversation Design</span>
            <select
              name="conversation_design_id"
              value={form.conversation_design_id}
              onChange={updateField}
            >
              {(conversationDesigns.length
                ? conversationDesigns
                : [{ id: "viewing_first_v1", name: "Viewing first" }]
              ).map((design) => (
                <option key={design.id} value={design.id}>
                  {design.name}
                </option>
              ))}
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
            {starting ? "Starting…" : "Start Interactive Session"}
          </button>
        </form>

        <form className="stack" onSubmit={handleSend}>
          <label className="field">
            <span>Actor message</span>
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
            {sending ? "Sending…" : "Send Message"}
          </button>
        </form>

        <div className="status">
          {activeSession
            ? `Active session: ${activeSession.session_id} (${activeSession.start_mode})`
            : "Start an interactive session to respond as the landlord."}
        </div>
        {error ? <p className="status error">{error}</p> : null}
      </div>
    </Panel>
  );
}
