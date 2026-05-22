import { useEffect, useState } from "react";

import {
  compareDesigns,
  fetchConversationDesigns,
  fetchInteractiveScenarios,
  fetchInteractiveSession,
  fetchResults,
  fetchScenarios,
  fetchSession,
  fetchSessions,
  runSimulation,
  sendInteractiveMessage,
  startInteractiveSession,
} from "./api";
import EvaluationScorecard from "./components/EvaluationScorecard";
import CompareDesignsPanel from "./components/CompareDesignsPanel";
import ConversationStatePanel from "./components/ConversationStatePanel";
import EventTimeline from "./components/EventTimeline";
import InteractivePanel from "./components/InteractivePanel";
import PromptCompletionInspector from "./components/PromptCompletionInspector";
import ReplayViewer from "./components/ReplayViewer";
import RunPanel from "./components/RunPanel";
import RuntimeContextPanel from "./components/RuntimeContextPanel";
import SessionList from "./components/SessionList";
import SetupCard from "./components/SetupCard";
import TranscriptViewer from "./components/TranscriptViewer";

export default function App() {
  const [viewerMode, setViewerMode] = useState("audit");
  const [mode, setMode] = useState("interactive");
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedSession, setSelectedSession] = useState(null);
  const [selectedResults, setSelectedResults] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [conversationDesigns, setConversationDesigns] = useState([]);
  const [conversationScenarios, setConversationScenarios] = useState([]);
  const [interactiveScenarios, setInteractiveScenarios] = useState([]);

  const isAuditMode = viewerMode === "audit";
  const filteredSessions = sessions.filter((session) => {
    const sessionMode = session.mode || "simulation";
    if (isAuditMode) return sessionMode === "interactive";
    return sessionMode === mode;
  });

  async function refreshSessions(nextSelectedSessionId) {
    setSessionsLoading(true);
    setSessionsError("");
    try {
      const nextSessions = await fetchSessions();
      setSessions(nextSessions);
      const desiredSessionId =
        nextSelectedSessionId || selectedSessionId || nextSessions[0]?.session_id || "";
      if (desiredSessionId) {
        await handleSelectSession(desiredSessionId);
      } else {
        setSelectedSession(null);
        setSelectedResults(null);
      }
    } catch (error) {
      setSessionsError(error.message);
    } finally {
      setSessionsLoading(false);
    }
  }

  async function handleSelectSession(sessionId) {
    setSelectedSessionId(sessionId);
    setDetailLoading(true);
    setDetailError("");
    try {
      const sessionSummary = sessions.find((entry) => entry.session_id === sessionId);
      const modeForSession = sessionSummary?.mode || mode;
      const sessionPromise =
        modeForSession === "interactive"
          ? fetchInteractiveSession(sessionId)
          : fetchSession(sessionId);
      const [session, results] = await Promise.all([sessionPromise, fetchResults(sessionId)]);
      setSelectedSession(session);
      setSelectedResults(results);
    } catch (error) {
      setDetailError(error.message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleRun(payload) {
    const artifact = await runSimulation(payload);
    setViewerMode("dev");
    setMode("simulation");
    setSelectedSessionId(artifact.session_id);
    setSelectedSession(artifact);
    setSelectedResults(await fetchResults(artifact.session_id));
    await refreshSessions(artifact.session_id);
  }

  async function handleStartInteractive(payload) {
    const { session_id: sessionId } = await startInteractiveSession(payload);
    setMode("interactive");
    await refreshSessions(sessionId);
  }

  async function handleSendInteractive(sessionId, message) {
    const artifact = await sendInteractiveMessage(sessionId, message);
    setSelectedSessionId(artifact.session_id);
    setSelectedSession(artifact);
    setSelectedResults(await fetchResults(artifact.session_id));
    await refreshSessions(artifact.session_id);
  }

  useEffect(() => {
    refreshSessions();
    fetchConversationDesigns()
      .then(setConversationDesigns)
      .catch(() => setConversationDesigns([]));
    fetchScenarios()
      .then(setConversationScenarios)
      .catch(() => setConversationScenarios([]));
    fetchInteractiveScenarios()
      .then(setInteractiveScenarios)
      .catch(() => setInteractiveScenarios([]));
  }, []);

  useEffect(() => {
    if (isAuditMode) setMode("interactive");
  }, [isAuditMode]);

  useEffect(() => {
    if (!selectedSessionId) return;
    const selectedSessionSummary = sessions.find(
      (session) => session.session_id === selectedSessionId,
    );
    if (selectedSessionSummary && (selectedSessionSummary.mode || "simulation") === mode) return;
    const fallbackSessionId = filteredSessions[0]?.session_id || "";
    if (fallbackSessionId) {
      handleSelectSession(fallbackSessionId);
      return;
    }
    setSelectedSessionId("");
    setSelectedSession(null);
    setSelectedResults(null);
  }, [viewerMode, mode, sessions]);

  const phoneCaptured = Boolean(
    selectedSession?.runtime_context?.extracted_entities?.phone,
  );

  const activeInteractiveSession =
    selectedSession?.mode === "interactive" ? selectedSession : null;

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="header-copy">
          <p className="eyebrow">Client testing workspace</p>
          <h1>Test Rental Conversations</h1>
          <p className="subtitle">
            Reply as the landlord and watch how the AI moves the conversation forward.
          </p>
        </div>
        <button
          type="button"
          className="header-dev-toggle"
          onClick={() => setViewerMode(isAuditMode ? "dev" : "audit")}
        >
          {isAuditMode ? "Advanced →" : "← Test mode"}
        </button>
      </header>

      {!isAuditMode ? (
        <div className="mode-toggle" role="tablist" aria-label="Run mode">
          <button
            type="button"
            className={mode === "interactive" ? "mode-button active" : "mode-button"}
            onClick={() => setMode("interactive")}
          >
            Interactive
          </button>
          <button
            type="button"
            className={mode === "simulation" ? "mode-button active" : "mode-button"}
            onClick={() => setMode("simulation")}
          >
            Simulation
          </button>
        </div>
      ) : null}

      <div className="layout">
        <aside className="sidebar">
          {!isAuditMode && mode === "simulation" ? (
            <RunPanel onRun={handleRun} />
          ) : !isAuditMode ? (
            <InteractivePanel
              activeSession={activeInteractiveSession}
              onStart={handleStartInteractive}
              onSend={handleSendInteractive}
              auditMode={false}
              conversationDesigns={conversationDesigns}
              interactiveScenarios={interactiveScenarios}
            />
          ) : null}

          <SessionList
            sessions={filteredSessions}
            selectedSessionId={selectedSessionId}
            loading={sessionsLoading}
            error={sessionsError}
            onRefresh={() => refreshSessions()}
            onSelect={handleSelectSession}
            auditMode={isAuditMode}
            scenarioLabels={Object.fromEntries(
              interactiveScenarios.map((s) => [
                s.scenario_id,
                s.property?.title || s.title,
              ])
            )}
          />

          {isAuditMode ? (
            <details className="compare-details">
              <summary className="compare-summary">Compare message styles</summary>
              <CompareDesignsPanel
                conversationDesigns={conversationDesigns}
                conversationScenarios={conversationScenarios}
                onCompare={compareDesigns}
              />
            </details>
          ) : null}
        </aside>

        <section className="detail-column">
          {detailLoading ? <p className="status">Loading conversation…</p> : null}
          {detailError ? <p className="status error">{detailError}</p> : null}

          {isAuditMode ? <SetupCard setup={selectedSession?.setup} /> : null}

          {isAuditMode ? (
            <div className="chat-shell">
              <div className="chat-shell-header">Conversation</div>
              <TranscriptViewer
                transcript={selectedSession?.transcript}
                events={selectedSession?.events}
                auditMode={true}
                bare={true}
              />
              <InteractivePanel
                activeSession={activeInteractiveSession}
                onStart={handleStartInteractive}
                onSend={handleSendInteractive}
                auditMode={true}
                conversationDesigns={conversationDesigns}
                interactiveScenarios={interactiveScenarios}
              />
            </div>
          ) : (
            <TranscriptViewer
              transcript={selectedSession?.transcript}
              events={selectedSession?.events}
              auditMode={false}
            />
          )}

          <EvaluationScorecard
            evaluation={selectedResults?.evaluation}
            failureTypes={selectedResults?.failure_types}
            auditMode={isAuditMode}
            phoneCaptured={phoneCaptured}
            conversationDesignName={selectedSession?.conversation_design_name}
          />

          {isAuditMode ? (
            <ConversationStatePanel
              conversationState={
                selectedSession?.conversation_state || selectedResults?.conversation_state
              }
            />
          ) : null}

          {!isAuditMode ? (
            <>
              <RuntimeContextPanel runtimeContext={selectedSession?.runtime_context} />
              <PromptCompletionInspector
                session={selectedSession}
                observability={selectedResults?.observability}
              />
              <EventTimeline events={selectedSession?.events} />
              <ReplayViewer replayOutput={selectedSession?.replay_output} />
            </>
          ) : null}
        </section>
      </div>
    </main>
  );
}
