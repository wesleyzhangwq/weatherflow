import { useMemo } from "react";
import { WeatherFlowClient } from "./bridge";
import { Capsule } from "./components/Capsule";
import { Companion } from "./components/Companion";
import { nativeWindows } from "./native";
import { surfaceFromLocation } from "./surface";
import { useDesktopSnapshot } from "./useDesktopSnapshot";
import "./styles.css";

export function App() {
  const client = useMemo(() => new WeatherFlowClient(), []);
  const { snapshot, offline } = useDesktopSnapshot(client);
  const surface = surfaceFromLocation(window.location.search);
  if (surface === "capsule") return <Capsule client={client} onAccepted={nativeWindows.closeCapsule} />;
  if (surface === "cockpit") return <main className="cockpit-shell">Cockpit</main>;
  return <Companion snapshot={snapshot} offline={offline} onOpenCapsule={nativeWindows.openCapsule} onOpenCockpit={nativeWindows.openCockpit} />;
}
