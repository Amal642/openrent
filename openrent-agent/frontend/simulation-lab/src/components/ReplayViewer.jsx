import Panel from "./Panel";

export default function ReplayViewer({ replayOutput }) {
  return (
    <Panel title="Replay Viewer">
      <pre className="code-block">{replayOutput || "No replay output available."}</pre>
    </Panel>
  );
}
