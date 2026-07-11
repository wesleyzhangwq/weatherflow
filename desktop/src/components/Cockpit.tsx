import { useCallback, useEffect, useState } from "react";
import { WeatherFlowClient } from "../bridge";
import type { Approval, Artifact, DesktopSnapshot, LedgerEvent, ResetPreview, SystemStatus } from "../types";

interface CockpitProps { client: WeatherFlowClient; snapshot: DesktopSnapshot | null; offline: boolean }

export function Cockpit({ client, snapshot, offline }: CockpitProps) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [timeline, setTimeline] = useState<LedgerEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [resetPreview, setResetPreview] = useState<ResetPreview | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const run = snapshot?.latest_run;
  const refresh = useCallback(async () => {
    const [pending, status] = await Promise.all([client.approvals(), client.status()]);
    setApprovals(pending);
    setSystem(status);
    if (run) {
      const [events, files] = await Promise.all([client.timeline(run.id), client.artifacts(run.id)]);
      setTimeline(events);
      setArtifacts(files);
    }
  }, [client, run]);
  useEffect(() => { void refresh(); }, [refresh]);

  const decide = async (approval: Approval, decision: "approve" | "deny") => {
    await client.decide(approval.id, decision, approval.version);
    await refresh();
  };
  const exportDiagnostics = async () => {
    const result = await client.exportDiagnostics();
    setOperation(`Diagnostic saved locally: ${result.path}`);
  };
  const reviewBehaviorReset = async () => {
    setResetPreview(await client.previewReset("behavior"));
  };
  const resetBehavior = async () => {
    const result = await client.reset("behavior");
    setResetPreview(null);
    setOperation(`Deleted ${result.deleted_count} behavior records.`);
  };
  const completeOnboarding = async () => {
    await client.completeOnboarding(true);
    setSystem(await client.status());
    setOperation("Local ownership confirmed. Metadata-only sensing is enabled.");
  };

  return (
    <main className="cockpit-shell">
      <header className="cockpit-header">
        <div><span className="eyebrow">WEATHERFLOW</span><h1>Daily cockpit</h1></div>
        <span className={`daemon-state ${offline ? "offline" : "online"}`}>{offline ? "Daemon offline" : "Local & private"}</span>
      </header>
      <div className="cockpit-grid">
        <section className="panel current-panel">
          <span className="panel-label">Current rhythm</span>
          <h2>{snapshot?.rhythm.snapshot.summary ?? "Gathering gentle signals"}</h2>
          <div className="weather-chip" data-scene={snapshot?.rhythm.weather.scene ?? "mixed"}>{snapshot?.rhythm.weather.scene ?? "mixed"}</div>
          <p>Weather changes how WeatherFlow works with you. It never changes your goal.</p>
        </section>
        <section className="panel run-panel">
          <span className="panel-label">Active task</span>
          {run ? <><h2>{run.user_intent}</h2><span className={`status-pill ${run.status}`}>{run.status.replaceAll("_", " ")}</span>{run.result_summary && <p>{run.result_summary}</p>}</> : <p>No active Run.</p>}
        </section>
        <section className="panel approvals-panel">
          <span className="panel-label">Approvals</span>
          {approvals.filter((item) => item.status === "pending").length === 0 && <p>Nothing needs your attention.</p>}
          {approvals.filter((item) => item.status === "pending").map((approval) => (
            <article className="approval-row" key={approval.id}>
              <div className="approval-preview">
                <strong>{approval.tool_id}</strong>
                <small>{approval.effect} · {approval.action_id}</small>
                <pre>{JSON.stringify(approval.preview, null, 2)}</pre>
              </div>
              <div><button onClick={() => void decide(approval, "deny")}>Deny</button><button className="primary" onClick={() => void decide(approval, "approve")}>Approve</button></div>
            </article>
          ))}
        </section>
        <section className="panel artifacts-panel">
          <span className="panel-label">Artifacts</span>
          {artifacts.length === 0 ? <p>No artifacts yet.</p> : artifacts.map((artifact) => <a key={artifact.id} href={`/v1/artifacts/${artifact.id}/content`}>{artifact.name}<small>{artifact.media_type} · {artifact.size_bytes} bytes</small></a>)}
        </section>
        <section className="panel timeline-panel">
          <span className="panel-label">Run timeline & evidence</span>
          <ol>{timeline.slice(-8).reverse().map((event) => <li key={event.id}><i /><div><strong>{event.type.replaceAll(".", " ")}</strong><time>{new Date(event.recorded_at).toLocaleTimeString()}</time></div></li>)}</ol>
        </section>
        <section className="panel settings-panel">
          <span className="panel-label">Settings & diagnostics</span>
          {system && !system.onboarding_completed && <div className="onboarding-card"><strong>Your data stays on this Mac</strong><p>WeatherFlow captures coarse activity metadata only. It never captures screenshots, window titles, clipboard content, or keystrokes.</p><button className="primary" onClick={() => void completeOnboarding()}>Confirm local setup</button></div>}
          <dl><div><dt>Proactivity</dt><dd>Silent</dd></div><div><dt>Behavior sensor</dt><dd>{system?.behavior_sensor.mode === "metadata_only" ? "Metadata only" : "Checking"}</dd></div><div><dt>Data ownership</dt><dd>{system?.local_only ? "Local only · no telemetry upload" : "Checking"}</dd></div><div><dt>Packs</dt><dd>{system?.installed_packs.join(", ") || "None"}</dd></div><div><dt>Bridge</dt><dd>{offline ? "Recovering" : "Authenticated loopback"}</dd></div></dl>
          <div className="settings-actions">
            <button onClick={() => void exportDiagnostics()}>Export local diagnostics</button>
            {!resetPreview && <button onClick={() => void reviewBehaviorReset()}>Review behavior reset</button>}
            {resetPreview && <button onClick={() => void resetBehavior()}>Delete {resetPreview.count} behavior records</button>}
          </div>
          {operation && <small role="status">{operation}</small>}
        </section>
      </div>
    </main>
  );
}
