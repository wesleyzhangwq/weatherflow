import { useEffect, useState } from "react";
import { resolveBridgeConfig, WeatherFlowClient } from "./bridge";
import { useActivityMetadata } from "./activity";
import { Capsule } from "./components/Capsule";
import { Companion } from "./components/Companion";
import { Cockpit } from "./components/Cockpit";
import { nativeWindows } from "./native";
import { surfaceFromLocation } from "./surface";
import { useDesktopSnapshot } from "./useDesktopSnapshot";
import { useWorkspaces } from "./useWorkspaces";
import "./styles.css";

export function App() {
  const [client, setClient] = useState<WeatherFlowClient | null>(null);
  const [bridgeError, setBridgeError] = useState(false);

  useEffect(() => {
    let alive = true;
    void resolveBridgeConfig()
      .then((config) => { if (alive) setClient(new WeatherFlowClient(config)); })
      .catch(() => { if (alive) setBridgeError(true); });
    return () => { alive = false; };
  }, []);

  if (!client) {
    return <main className="bridge-boot" role="status">{bridgeError ? "WeatherFlow daemon unavailable" : "Starting WeatherFlow…"}</main>;
  }
  return <ConnectedApp client={client} />;
}

function ConnectedApp({ client }: { client: WeatherFlowClient }) {
  const workspace = useWorkspaces(client);
  const { snapshot, offline } = useDesktopSnapshot(client, workspace.selectedId);
  const surface = surfaceFromLocation(window.location.search);
  const sensorAvailable = useActivityMetadata(client, surface === "companion", workspace.selectedId);
  if (surface === "capsule") return <Capsule client={client} workspaceId={workspace.selectedId} onAccepted={nativeWindows.closeCapsule} onCancel={nativeWindows.closeCapsule} />;
  if (surface === "cockpit") return <Cockpit client={client} snapshot={snapshot} offline={offline} workspaces={workspace.workspaces} selectedWorkspaceId={workspace.selectedId} onSelectWorkspace={workspace.select} onAuthorizeWorkspace={workspace.authorize} />;
  return <Companion snapshot={snapshot} offline={offline} sensorAvailable={sensorAvailable} onStartDrag={nativeWindows.startCompanionDrag} onOpenCapsule={nativeWindows.openCapsule} onOpenCockpit={nativeWindows.openCockpit} />;
}
