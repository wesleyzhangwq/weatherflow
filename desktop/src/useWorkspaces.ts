import { useCallback, useEffect, useState } from "react";
import { WeatherFlowClient } from "./bridge";
import type { Workspace } from "./types";

const SELECTED_WORKSPACE_KEY = "weatherflow.selectedWorkspaceId";

export function useWorkspaces(client: WeatherFlowClient) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem(SELECTED_WORKSPACE_KEY));

  const select = useCallback((workspaceId: string) => {
    localStorage.setItem(SELECTED_WORKSPACE_KEY, workspaceId);
    setSelectedId(workspaceId);
  }, []);

  const refresh = useCallback(async () => {
    const available = await client.workspaces();
    setWorkspaces(available);
    const remembered = localStorage.getItem(SELECTED_WORKSPACE_KEY);
    const selected = available.find((workspace) => workspace.id === remembered) ?? available[0];
    if (selected) select(selected.id);
    else {
      localStorage.removeItem(SELECTED_WORKSPACE_KEY);
      setSelectedId(null);
    }
    return available;
  }, [client, select]);

  const authorize = useCallback(async (path: string) => {
    const segments = path.split("/").filter(Boolean);
    const workspace = await client.authorizeWorkspace(segments.at(-1) ?? "Project", path);
    await refresh();
    select(workspace.id);
    return workspace;
  }, [client, refresh, select]);

  useEffect(() => { void refresh(); }, [refresh]);

  return { workspaces, selectedId, select, authorize, refresh };
}
