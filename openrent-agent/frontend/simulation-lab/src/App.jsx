import { useEffect, useState } from "react";

import {
  fetchInteractiveSession,
  fetchResults,
  fetchSession,
  fetchSessions,
  runSimulation,
  sendInteractiveMessage,
  startInteractiveSession,
} from "./api";
import EvaluationScorecard from "./components/EvaluationScorecard";
import EventTimeline from "./components/EventTimeline";
import InteractivePanel from "./components/InteractivePanel";
import PromptCompletionInspector from "./components/PromptCompletionInspector";
import ReplayViewer from "./components/ReplayViewer";
import RunPanel from "./components/RunPanel";
import RuntimeContextPanel from "./components/RuntimeContextPanel";
import SessionList from "./components/SessionList";
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

  const isAuditMode = viewerMode === "audit";
  const filteredSessions = sessions.filter((session) => {
    const sessionMode = session.mode || "simulation";
    if (isAuditMode) {
      return sessionMode === "interactive";
    }
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
      const sessionPromise = modeForSession === "interactive"
        ? fetchInteractiveSession(sessionId)
        : fetchSession(sessionId);
      const [session, results] = await Promise.all([
        sessionPromise,
        fetchResults(sessionId),
      ]);
      const bundle = { session, results };
      setSelectedSession(bundle.session);
      setSelectedResults(bundle.results);
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
  }, []);

  useEffect(() => {
    if (isAuditMode) {
      setMode("interactive");
    }
  }, [isAuditMode]);

  useEffect(() => {
    if (!selectedSessionId) {
      return;
    }
    const selectedSessionSummary = sessions.find(
      (session) => session.session_id === selectedSessionId,
    );
    if (selectedSessionSummary && (selectedSessionSummary.mode || "simulation") === mode) {
      return;
    }
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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">openrent-agent</p>
          <h1>Simulation Lab</h1>
        </div>
        <p className="subtitle">
          {isAuditMode
            ? "Audit-first landlord testing flow with shared session history."
            : "Full internal inspection UI over simulation session artifacts."}
        </p>
      </header>

      <div className="mode-toggle" role="tablist" aria-label="Simulation lab viewer mode">
        <button
          type="button"
          className={viewerMode === "audit" ? "mode-button active" : "mode-button"}
          onClick={() => setViewerMode("audit")}
        >
          Audit
        </button>
        <button
          type="button"
          className={viewerMode === "dev" ? "mode-button active" : "mode-button"}
          onClick={() => setViewerMode("dev")}
        >
          Dev
        </button>
      </div>

      {!isAuditMode ? (
        <div className="mode-toggle" role="tablist" aria-label="Simulation lab run mode">
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
          ) : (
            <InteractivePanel
              activeSession={selectedSession?.mode === "interactive" ? selectedSession : null}
              onStart={handleStartInteractive}
              onSend={handleSendInteractive}
              auditMode={isAuditMode}
            />
          )}
          <SessionList
            sessions={filteredSessions}
            selectedSessionId={selectedSessionId}
            loading={sessionsLoading}
            error={sessionsError}
            onRefresh={() => refreshSessions()}
            onSelect={handleSelectSession}
            auditMode={isAuditMode}
          />
        </aside>

        <section className="detail-column">
          {detailLoading ? <p className="status">Loading session detail...</p> : null}
          {detailError ? <p className="status error">{detailError}</p> : null}
          <TranscriptViewer
            transcript={selectedSession?.transcript}
            events={selectedSession?.events}
            auditMode={isAuditMode}
          />
          <EvaluationScorecard
            evaluation={selectedResults?.evaluation}
            failureTypes={selectedResults?.failure_types}
            auditMode={isAuditMode}
            phoneCaptured={phoneCaptured}
          />
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
