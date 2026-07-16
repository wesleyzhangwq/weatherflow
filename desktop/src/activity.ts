import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { WeatherFlowClient } from "./bridge";
import type { ActivityHeartbeat } from "./types";

export interface NativeActivitySample {
  idle_seconds: number;
  app_name: string;
  bundle_id: string;
  window_title: string | null;
  focused: boolean;
  idle_state: "active" | "idle";
  category: "development" | "communication" | "research" | "planning" | "creative" | "other";
  accessibility: "granted" | "denied";
}

export function nativeSampleToHeartbeat(
  sample: NativeActivitySample,
  observedAt: Date,
  eventId: string,
  deviceId: string,
): ActivityHeartbeat {
  return {
    source: "macos_window",
    device_id: deviceId,
    source_instance: "weatherflow-desktop",
    source_event_id: eventId,
    observed_at: observedAt.toISOString(),
    pulsetime_seconds: 15,
    app_name: sample.app_name,
    bundle_id: sample.bundle_id,
    window_title: sample.window_title,
    focused: sample.focused,
    idle_state: sample.idle_state,
    category: sample.category,
  };
}

async function sample(): Promise<NativeActivitySample> {
  if (!("__TAURI_INTERNALS__" in window)) throw new Error("native activity unavailable");
  return invoke<NativeActivitySample>("sample_activity_metadata");
}

export async function nativeActivityPermission(): Promise<"granted" | "denied" | "unavailable"> {
  if (!("__TAURI_INTERNALS__" in window)) return "unavailable";
  try {
    return (await sample()).accessibility;
  } catch {
    return "unavailable";
  }
}

function installationDeviceId(): string {
  const key = "weatherflow.activity.device-id";
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const created = globalThis.crypto?.randomUUID?.() ?? `desktop-${Date.now()}`;
    window.localStorage.setItem(key, created);
    return created;
  } catch {
    return "weatherflow-desktop";
  }
}

function eventId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `native-${Date.now()}`;
}

export function useActivityMetadata(
  client: WeatherFlowClient,
  enabled: boolean,
  workspaceId?: string | null,
) {
  void workspaceId;
  const [available, setAvailable] = useState(true);
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let polling = false;
    let timer: number | null = null;
    const deviceId = installationDeviceId();
    const capture = () => {
      if (polling) return;
      polling = true;
      void client.activityPreferences()
        .then(async (preferences) => {
          if (stopped) return;
          if (!preferences.collection_enabled || !preferences.macos_enabled) {
            setAvailable(true);
            return;
          }
          const value = await sample();
          setAvailable(true);
          await client.ingestActivityHeartbeat(
            nativeSampleToHeartbeat(value, new Date(), eventId(), deviceId),
          );
        })
        .catch(() => setAvailable(false))
        .finally(() => { polling = false; });
    };
    capture();
    timer = window.setInterval(capture, 5_000);

    return () => {
      stopped = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [client, enabled]);
  return available;
}
