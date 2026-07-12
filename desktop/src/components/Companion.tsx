import type { DesktopSnapshot, RunStatus, WeatherScene } from "../types";

interface CompanionProps {
  snapshot: DesktopSnapshot | null;
  offline?: boolean;
  sensorAvailable?: boolean;
  onOpenCapsule: () => void;
  onOpenCockpit: () => void;
}

function ringState(status?: RunStatus): string {
  if (!status || ["succeeded", "cancelled"].includes(status)) return "idle";
  if (["queued", "planning", "running"].includes(status)) return "active";
  if (status === "waiting_approval") return "approval";
  if (["paused", "waiting_user"].includes(status)) return "paused";
  return "attention";
}

export function Companion({ snapshot, offline = false, sensorAvailable = true, onOpenCapsule, onOpenCockpit }: CompanionProps) {
  const weather: WeatherScene = snapshot?.rhythm.weather.scene ?? "mixed";
  const ring = offline ? "offline" : ringState(snapshot?.latest_run?.status);
  return (
    <main className="companion-shell" data-weather={weather} data-ring={ring}>
      <button className="companion-character" aria-label="Open command capsule" onClick={onOpenCapsule}>
        <span className="weather-layer" aria-hidden="true">
          <span className="weather-orbit" />
          <span className="weather-particle particle-one" />
          <span className="weather-particle particle-two" />
        </span>
        <span className="run-ring" aria-hidden="true" />
        <span className="character-body" aria-hidden="true">
          <span className="character-face"><i /><i /></span>
        </span>
        {ring === "approval" && <span className="approval-badge" aria-label="Approval waiting">!</span>}
      </button>
      {snapshot?.metadata_sensor_enabled && !sensorAvailable && <span className="sensor-unavailable" role="status">Activity signal unavailable</span>}
      <button className="cockpit-trigger" aria-label="Open Cockpit" onClick={onOpenCockpit}>⌁</button>
    </main>
  );
}
