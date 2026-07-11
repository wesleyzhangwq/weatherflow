import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { WeatherFlowClient } from "./bridge";

export interface NativeActivitySample { idle_seconds: number; category: "development" | "communication" | "research" | "planning" | "creative" | "other" }

export class ActivityAccumulator {
  private activeSeconds = 0;
  private idleSeconds = 0;
  private switches = 0;
  private previousCategory: string | null = null;
  private categories: Record<string, number> = {};
  private windowStart: Date;

  constructor(start: Date = new Date()) { this.windowStart = start; }

  record(sample: NativeActivitySample, elapsedSeconds: number) {
    const idle = Math.min(Math.max(sample.idle_seconds, 0), elapsedSeconds);
    const active = Math.max(0, elapsedSeconds - idle);
    this.idleSeconds += idle;
    this.activeSeconds += active;
    this.categories[sample.category] = (this.categories[sample.category] ?? 0) + active;
    if (this.previousCategory && this.previousCategory !== sample.category) this.switches += 1;
    this.previousCategory = sample.category;
  }

  flush(end: Date = new Date()) {
    const payload = {
      kind: "activity_metadata",
      observed_at: end.toISOString(),
      window_start: this.windowStart.toISOString(),
      window_end: end.toISOString(),
      active_seconds: Math.round(this.activeSeconds),
      idle_seconds: Math.round(this.idleSeconds),
      app_switch_count: this.switches,
      category_seconds: Object.fromEntries(Object.entries(this.categories).map(([key, value]) => [key, Math.round(value)])),
    };
    this.activeSeconds = 0; this.idleSeconds = 0; this.switches = 0; this.categories = {}; this.windowStart = end;
    return payload;
  }
}

async function sample(): Promise<NativeActivitySample> {
  if (!("__TAURI_INTERNALS__" in window)) throw new Error("native activity unavailable");
  return invoke<NativeActivitySample>("sample_activity_metadata");
}

export function useActivityMetadata(client: WeatherFlowClient, enabled: boolean) {
  const [available, setAvailable] = useState(true);
  useEffect(() => {
    if (!enabled) return;
    const accumulator = new ActivityAccumulator();
    let seconds = 0;
    const timer = window.setInterval(() => {
      void sample().then((value) => {
        setAvailable(true); accumulator.record(value, 5); seconds += 5;
        if (seconds >= 60) { seconds = 0; void client.ingestSignal(accumulator.flush()); }
      }).catch(() => setAvailable(false));
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [client, enabled]);
  return available;
}
