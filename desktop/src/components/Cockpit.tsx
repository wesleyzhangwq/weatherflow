import { useCallback, useEffect, useState } from "react";
import { WeatherFlowClient } from "../bridge";
import type { Approval, Artifact, DesktopSnapshot, LedgerEvent } from "../types";

interface CockpitProps { client: WeatherFlowClient; snapshot: DesktopSnapshot | null; offline: boolean }

export function Cockpit({ client, snapshot, offline }: CockpitProps) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [timeline, setTimeline] = useState<LedgerEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const run = snapshot?.latest_run;
  const refresh = useCallback(async () => {
    setApprovals(await client.approvals());
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
              <div><strong>Action waiting</strong><small>{approval.action_id}</small></div>
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
          <dl><div><dt>Proactivity</dt><dd>Silent</dd></div><div><dt>Motion</dt><dd>System preference</dd></div><div><dt>Bridge</dt><dd>{offline ? "Recovering" : "Authenticated loopback"}</dd></div></dl>
        </section>
      </div>
    </main>
  );
}
