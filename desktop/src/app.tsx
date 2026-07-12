import { useMemo } from "react";
import { WeatherFlowClient } from "./bridge";
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
  const client = useMemo(() => new WeatherFlowClient(), []);
  const workspace = useWorkspaces(client);
  const { snapshot, offline } = useDesktopSnapshot(client, workspace.selectedId);
  const surface = surfaceFromLocation(window.location.search);
  const sensorAvailable = useActivityMetadata(client, surface === "companion" && snapshot?.metadata_sensor_enabled === true, workspace.selectedId);
  if (surface === "capsule") return <Capsule client={client} workspaceId={workspace.selectedId} onAccepted={nativeWindows.closeCapsule} />;
  if (surface === "cockpit") return <Cockpit client={client} snapshot={snapshot} offline={offline} workspaces={workspace.workspaces} selectedWorkspaceId={workspace.selectedId} onSelectWorkspace={workspace.select} onAuthorizeWorkspace={workspace.authorize} />;
  return <Companion snapshot={snapshot} offline={offline} sensorAvailable={sensorAvailable} onOpenCapsule={nativeWindows.openCapsule} onOpenCockpit={nativeWindows.openCockpit} />;
}
