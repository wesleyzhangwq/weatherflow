import { useEffect, useState } from "react";
import { WeatherFlowClient } from "./bridge";
import type { DesktopSnapshot } from "./types";

export function useDesktopSnapshot(client: WeatherFlowClient) {
  const [snapshot, setSnapshot] = useState<DesktopSnapshot | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;
    let cursor: string | null = null;
    const refresh = async () => {
      try {
        const next = await client.snapshot();
        if (alive) { setSnapshot(next); setOffline(false); }
      } catch { if (alive) setOffline(true); }
    };
    void refresh();
    const socket = client.events(
      cursor,
      (event) => { cursor = event.id; void refresh(); },
      () => { cursor = null; void refresh(); },
    );
    return () => { alive = false; socket?.close(); };
  }, [client]);

  return { snapshot, offline };
}
