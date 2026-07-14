import { useRef, type MouseEvent } from "react";
import {
  Cloud,
  CloudFog,
  CloudLightning,
  CloudSun,
  MoonStars,
  Sun,
} from "@phosphor-icons/react";
import type { DesktopSnapshot, RunStatus, WeatherScene } from "../types";

interface CompanionProps {
  snapshot: DesktopSnapshot | null;
  offline?: boolean;
  sensorAvailable?: boolean;
  onStartDrag: () => void | Promise<void>;
  onOpenCapsule: () => void;
  onOpenCockpit: () => void;
}

const weatherIcons = {
  clear: Sun,
  fair: CloudSun,
  fog: CloudFog,
  storm: CloudLightning,
  still: Cloud,
  night: MoonStars,
  mixed: CloudSun,
} satisfies Record<WeatherScene, typeof Sun>;

const weatherLabels: Record<WeatherScene, string> = {
  clear: "晴朗",
  fair: "微晴",
  fog: "薄雾",
  storm: "风暴",
  still: "静滞",
  night: "夜色",
  mixed: "混合",
};

function runState(status?: RunStatus): string {
  if (!status || ["succeeded", "cancelled"].includes(status)) return "idle";
  if (["queued", "planning", "running"].includes(status)) return "active";
  if (status === "waiting_approval") return "approval";
  if (["paused", "waiting_user"].includes(status)) return "paused";
  return "attention";
}

export function Companion({ snapshot, offline = false, sensorAvailable = true, onStartDrag, onOpenCapsule, onOpenCockpit }: CompanionProps) {
  const weather: WeatherScene = snapshot?.rhythm.weather.scene ?? "mixed";
  const state = offline ? "offline" : runState(snapshot?.latest_run?.status);
  const WeatherIcon = weatherIcons[weather];
  const pointerOrigin = useRef<{ x: number; y: number } | null>(null);
  const dragged = useRef(false);

  const pointerDown = (event: MouseEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    pointerOrigin.current = { x: event.clientX, y: event.clientY };
    dragged.current = false;
  };
  const pointerMove = (event: MouseEvent<HTMLButtonElement>) => {
    const origin = pointerOrigin.current;
    if (!origin || dragged.current) return;
    if ((event.buttons & 1) === 0) {
      pointerOrigin.current = null;
      return;
    }
    if (Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < 5) return;
    dragged.current = true;
    pointerOrigin.current = null;
    void onStartDrag();
  };
  const pointerUp = () => {
    pointerOrigin.current = null;
    if (dragged.current) window.setTimeout(() => { dragged.current = false; }, 0);
  };
  const click = () => {
    if (dragged.current) return;
    onOpenCapsule();
  };

  return (
    <main className="companion-shell" data-weather={weather} data-agent-state={state}>
      <button
        className="weather-button weather-tile"
        data-shape="square"
        aria-label={`当前天气：${weatherLabels[weather]}`}
        title={`${weatherLabels[weather]} · 点击输入，拖动移动`}
        onMouseDown={pointerDown}
        onMouseMove={pointerMove}
        onMouseUp={pointerUp}
        onMouseLeave={() => { pointerOrigin.current = null; }}
        onClick={click}
        onContextMenu={(event) => { event.preventDefault(); onOpenCockpit(); }}
      >
        <WeatherIcon className="weather-symbol" weight="duotone" aria-hidden="true" />
      </button>
      {state !== "idle" && (
        <button
          className="task-status"
          data-state={state}
          aria-label={state === "approval" ? "等待批准" : "查看任务状态"}
          onClick={onOpenCockpit}
        />
      )}
      {snapshot?.metadata_sensor_enabled && !sensorAvailable && (
        <span className="sensor-unavailable" role="status" aria-label="行为信号暂不可用" />
      )}
    </main>
  );
}
