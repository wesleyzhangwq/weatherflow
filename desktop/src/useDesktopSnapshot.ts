import { useEffect, useState } from "react";
import { WeatherFlowClient } from "./bridge";
import type { DesktopSnapshot } from "./types";

export function useDesktopSnapshot(client: WeatherFlowClient, workspaceId?: string | null) {
  const [snapshot, setSnapshot] = useState<DesktopSnapshot | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;
    let cursor: string | null = null;
    let refreshTimer: number | null = null;
    const refresh = async () => {
      try {
        const next = await client.snapshot(workspaceId);
        if (alive) { setSnapshot(next); setOffline(false); }
      } catch { if (alive) setOffline(true); }
    };
    const scheduleRefresh = () => {
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        refreshTimer = null;
        void refresh();
      }, 75);
    };
    void refresh();
    const socket = client.events(
      cursor,
      (event) => { cursor = event.id; scheduleRefresh(); },
      () => { cursor = null; scheduleRefresh(); },
    );
    return () => {
      alive = false;
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
      socket?.close();
    };
  }, [client, workspaceId]);

  return { snapshot, offline };
}
