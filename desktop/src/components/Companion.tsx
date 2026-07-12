import type { DesktopSnapshot, RunStatus, WeatherScene } from "../types";
import { AppWindow } from "@phosphor-icons/react";
import companionIcon from "../../src-tauri/icons/icon.png";

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
      <div className="companion-drag-surface" data-tauri-drag-region aria-label="拖动悬浮天气" />
      <button className="companion-character" aria-label="打开指令输入框" onClick={onOpenCapsule}>
        <span className="weather-layer" aria-hidden="true">
          <span className="weather-orbit" />
          <span className="weather-particle particle-one" />
          <span className="weather-particle particle-two" />
        </span>
        <span className="run-ring" aria-hidden="true" />
        <img className="character-image" src={companionIcon} alt="" draggable={false} />
        {ring === "approval" && <span className="approval-badge" aria-label="等待批准">!</span>}
      </button>
      {snapshot?.metadata_sensor_enabled && !sensorAvailable && <span className="sensor-unavailable" role="status">行为信号暂不可用</span>}
      <button className="cockpit-trigger" aria-label="打开控制台" onClick={onOpenCockpit}><AppWindow weight="bold" /></button>
    </main>
  );
}
