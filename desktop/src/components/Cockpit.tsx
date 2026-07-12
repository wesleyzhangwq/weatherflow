import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { WeatherFlowClient } from "../bridge";
import { nativeWindows } from "../native";
import type { Approval, Artifact, DesktopSnapshot, LedgerEvent, ResetPreview, Run, SystemStatus, Workspace } from "../types";

interface CockpitProps {
  client: WeatherFlowClient;
  snapshot: DesktopSnapshot | null;
  offline: boolean;
  workspaces?: Workspace[];
  selectedWorkspaceId?: string | null;
  onSelectWorkspace?: (workspaceId: string) => void;
  onAuthorizeWorkspace?: (path: string) => Promise<Workspace>;
}

export function Cockpit({ client, snapshot, offline, workspaces = [], selectedWorkspaceId, onSelectWorkspace, onAuthorizeWorkspace }: CockpitProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [timeline, setTimeline] = useState<LedgerEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [resetPreview, setResetPreview] = useState<ResetPreview | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [rhythmText, setRhythmText] = useState("");
  const [rhythmKind, setRhythmKind] = useState<"checkin" | "correction">("checkin");
  const [followUp, setFollowUp] = useState("");
  const run = useMemo(() => runs.find((item) => item.id === selectedRunId) ?? runs[0] ?? snapshot?.latest_run ?? null, [runs, selectedRunId, snapshot]);

  const refresh = useCallback(async () => {
    const [pending, status, recent] = await Promise.all([
      client.approvals(),
      client.status(selectedWorkspaceId),
      client.runs(selectedWorkspaceId),
    ]);
    setRuns(recent);
    setApprovals(pending.filter((approval) => recent.some((item) => item.id === approval.run_id)));
    setSystem(status);
    const activeId = selectedRunId && recent.some((item) => item.id === selectedRunId) ? selectedRunId : recent[0]?.id;
    setSelectedRunId(activeId ?? null);
    if (activeId) {
      const [events, files] = await Promise.all([client.timeline(activeId), client.artifacts(activeId)]);
      setTimeline(events);
      setArtifacts(files);
    } else {
      setTimeline([]);
      setArtifacts([]);
    }
  }, [client, selectedRunId, selectedWorkspaceId]);
  useEffect(() => { void refresh(); }, [refresh, snapshot?.latest_run?.updated_at]);

  const decide = async (approval: Approval, decision: "approve" | "deny") => {
    await client.decide(approval.id, decision, approval.version);
    await refresh();
  };
  const chooseWorkspace = async () => {
    const path = await nativeWindows.chooseWorkspaceDirectory();
    if (!path || !onAuthorizeWorkspace) return;
    const workspace = await onAuthorizeWorkspace(path);
    setOperation(`Authorized ${workspace.name}: ${workspace.action_roots[0]}`);
  };
  const downloadArtifact = async (artifact: Artifact) => {
    const blob = await client.artifactContent(artifact.id);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = artifact.name;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const submitRhythm = async (event: FormEvent) => {
    event.preventDefault();
    const text = rhythmText.trim();
    if (!text) return;
    await client.ingestSignal({ kind: rhythmKind, text, observed_at: new Date().toISOString() }, selectedWorkspaceId);
    setRhythmText("");
    setOperation(rhythmKind === "correction" ? "Your correction replaced the current interpretation." : "Check-in added to the current rhythm.");
    await refresh();
  };
  const submitFollowUp = async (event: FormEvent) => {
    event.preventDefault();
    const intent = followUp.trim();
    if (!intent || !run) return;
    await client.createRun(intent, crypto.randomUUID(), selectedWorkspaceId, run.id);
    setFollowUp("");
    setOperation("Follow-up accepted and continuing in the background.");
    await refresh();
  };
  const cancelRun = async () => {
    if (!run) return;
    await client.cancel(run.id);
    setOperation("Run cancelled.");
    await refresh();
  };
  const exportDiagnostics = async () => {
    const result = await client.exportDiagnostics(selectedWorkspaceId);
    setOperation(`Diagnostic saved locally: ${result.path}`);
  };
  const reviewBehaviorReset = async () => setResetPreview(await client.previewReset("behavior", selectedWorkspaceId));
  const resetBehavior = async () => {
    const result = await client.reset("behavior", selectedWorkspaceId);
    setResetPreview(null);
    setOperation(`Deleted ${result.deleted_count} behavior records.`);
  };
  const completeOnboarding = async (enableMetadataSensor: boolean) => {
    await client.completeOnboarding(enableMetadataSensor, selectedWorkspaceId);
    setSystem(await client.status(selectedWorkspaceId));
    setOperation(enableMetadataSensor ? "Metadata-only sensing is enabled." : "Using deliberate check-ins only.");
  };

  return (
    <main className="cockpit-shell">
      <header className="cockpit-header">
        <div><span className="eyebrow">WEATHERFLOW</span><h1>Daily cockpit</h1></div>
        <div className="workspace-controls">
          <select aria-label="Active project" value={selectedWorkspaceId ?? ""} onChange={(event) => onSelectWorkspace?.(event.target.value)}>
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
          </select>
          <button onClick={() => void chooseWorkspace()}>Choose project…</button>
          <span className={`daemon-state ${offline ? "offline" : "online"}`}>{offline ? "Daemon offline" : "Local & private"}</span>
        </div>
      </header>
      <div className="cockpit-grid">
        <section className="panel current-panel">
          <span className="panel-label">Current rhythm</span>
          <h2>{snapshot?.rhythm.snapshot.summary ?? "Waiting for your check-in"}</h2>
          <div className="weather-chip" data-scene={snapshot?.rhythm.weather.scene ?? "mixed"}>{snapshot?.rhythm.weather.scene ?? "mixed"}</div>
          <p>Weather changes how WeatherFlow works with you. It never changes your goal.</p>
          <form className="rhythm-form" onSubmit={submitRhythm}>
            <select aria-label="Rhythm signal type" value={rhythmKind} onChange={(event) => setRhythmKind(event.target.value as "checkin" | "correction")}><option value="checkin">Check in</option><option value="correction">Correct WeatherFlow</option></select>
            <input aria-label="Rhythm check-in" value={rhythmText} onChange={(event) => setRhythmText(event.target.value)} placeholder="How are you actually doing?" />
            <button className="primary" type="submit">Save</button>
          </form>
        </section>
        <section className="panel run-panel">
          <span className="panel-label">Runs</span>
          <div className="run-history">
            {runs.slice(0, 8).map((item) => <button className={item.id === run?.id ? "selected" : ""} key={item.id} onClick={() => setSelectedRunId(item.id)}><span>{item.user_intent}</span><small>{item.status.replaceAll("_", " ")}</small></button>)}
          </div>
          {run ? <div className="run-result"><span className={`status-pill ${run.status}`}>{run.status.replaceAll("_", " ")}</span>{["queued", "planning", "running", "paused"].includes(run.status) && <button className="cancel-run" onClick={() => void cancelRun()}>Cancel Run</button>}{run.result_summary && <p>{run.result_summary}</p>}<form className="follow-up-form" onSubmit={submitFollowUp}><input aria-label="Follow up on selected Run" value={followUp} onChange={(event) => setFollowUp(event.target.value)} placeholder="Continue from this result…" /><button className="primary" type="submit">Continue</button></form></div> : <p>No Run yet. Choose a project, then press ⌘⇧Space to ask WeatherFlow to handle something.</p>}
        </section>
        <section className="panel approvals-panel">
          <span className="panel-label">Approvals</span>
          {approvals.filter((item) => item.status === "pending").length === 0 && <p>Nothing needs your attention.</p>}
          {approvals.filter((item) => item.status === "pending").map((approval) => (
            <article className="approval-row" key={approval.id}><div className="approval-preview"><strong>{approval.tool_id}</strong><small>{approval.effect} · {approval.action_id}</small><pre>{JSON.stringify(approval.preview, null, 2)}</pre></div><div><button onClick={() => void decide(approval, "deny")}>Deny</button><button className="primary" onClick={() => void decide(approval, "approve")}>Approve</button></div></article>
          ))}
        </section>
        <section className="panel artifacts-panel">
          <span className="panel-label">Artifacts</span>
          {artifacts.length === 0 ? <p>No artifacts yet.</p> : artifacts.map((artifact) => <button className="artifact-row" key={artifact.id} onClick={() => void downloadArtifact(artifact)}>{artifact.name}<small>{artifact.media_type} · {artifact.size_bytes} bytes</small></button>)}
        </section>
        <section className="panel timeline-panel">
          <span className="panel-label">Run timeline & evidence</span>
          <ol>{timeline.slice(-12).reverse().map((event) => <li key={event.id}><i /><div><strong>{event.type.replaceAll(".", " ")}</strong><time>{new Date(event.recorded_at).toLocaleTimeString()}</time></div></li>)}</ol>
        </section>
        <section className="panel settings-panel">
          <span className="panel-label">Settings & diagnostics</span>
          {system && !system.onboarding_completed && <div className="onboarding-card"><strong>Choose how WeatherFlow senses your state</strong><p>Deliberate check-ins always work. Optional sensing records coarse activity metadata only—never screenshots, window titles, clipboard content, or keystrokes.</p><div><button onClick={() => void completeOnboarding(false)}>Check-ins only</button><button className="primary" onClick={() => void completeOnboarding(true)}>Enable metadata</button></div></div>}
          <dl><div><dt>Project</dt><dd>{snapshot?.workspace.action_roots[0] ?? "Loading"}</dd></div><div><dt>Model</dt><dd>{system?.model?.configured ? `${system.model.provider} · ${system.model.model}` : "Echo smoke fallback"}</dd></div><div><dt>Proactivity</dt><dd>Silent</dd></div><div><dt>Behavior sensor</dt><dd>{system?.behavior_sensor.enabled ? "Metadata enabled" : "Check-ins only"}</dd></div><div><dt>Data ownership</dt><dd>{system?.local_only ? "Local only · no telemetry upload" : "Checking"}</dd></div><div><dt>Packs</dt><dd>{system?.installed_packs.join(", ") || "None"}</dd></div><div><dt>Bridge</dt><dd>{offline ? "Recovering" : "Authenticated loopback"}</dd></div></dl>
          <div className="settings-actions"><button onClick={() => void exportDiagnostics()}>Export local diagnostics</button>{!resetPreview && <button onClick={() => void reviewBehaviorReset()}>Review behavior reset</button>}{resetPreview && <button onClick={() => void resetBehavior()}>Delete {resetPreview.count} behavior records</button>}</div>
          {operation && <small role="status">{operation}</small>}
        </section>
      </div>
    </main>
  );
}
