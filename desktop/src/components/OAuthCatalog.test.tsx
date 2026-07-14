import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "../bridge";
import type { ConnectorKind, ConnectorStatus, DesktopSnapshot } from "../types";
import { Cockpit } from "./Cockpit";

const snapshot: DesktopSnapshot = {
  rhythm: {
    snapshot: { id: "rhythm-1", summary: "Steady rhythm", valid_until: "2099-01-01T00:00:00Z" },
    policy: { proactivity: "silent", work_mode: "normal" },
    weather: {
      scene: "fair",
      intensity: 0.5,
      transition: "steady",
      snapshot_id: "rhythm-1",
      valid_until: "2099-01-01T00:00:00Z",
      presentation_version: "v1",
    },
  },
  latest_run: null,
  workspace: { id: "w1", name: "WeatherFlow", action_roots: ["/tmp/w1"], installed_packs: [] },
  metadata_sensor_enabled: false,
};

const connectorKinds: ConnectorKind[] = [
  "github", "gmail", "google_calendar", "slack", "notion", "google_drive", "google_sheets", "outlook",
  "one_drive", "microsoft_teams", "linear", "jira", "confluence", "dropbox", "gitlab", "discord", "trello",
  "asana", "airtable", "clickup",
];

function connectorStatus(connector: ConnectorKind): ConnectorStatus {
  const supported = connector === "github" || connector === "gmail" || connector === "google_calendar";
  const connected = connector === "github" || connector === "slack";
  const labels: Record<ConnectorKind, string> = {
    github: "GitHub", gmail: "Gmail", google_calendar: "Google Calendar", slack: "Slack", notion: "Notion",
    google_drive: "Google Drive", google_sheets: "Google Sheets", outlook: "Outlook", one_drive: "OneDrive",
    microsoft_teams: "Microsoft Teams", linear: "Linear", jira: "Jira", confluence: "Confluence", dropbox: "Dropbox",
    gitlab: "GitLab", discord: "Discord", trello: "Trello", asana: "Asana", airtable: "Airtable", clickup: "ClickUp",
  };
  return {
    connector,
    label: labels[connector],
    category: ["gmail", "google_calendar", "slack", "outlook", "microsoft_teams", "discord"].includes(connector) ? "communication" : ["github", "gitlab", "linear", "jira"].includes(connector) ? "development" : "productivity",
    toolkit: connector,
    oauth_setup: connector === "trello" ? "bring_your_own" : "managed",
    phase: connected ? "active" : null,
    configured: true,
    connected,
    display_name: connected ? "Wesley" : null,
    auto_fetch_supported: supported,
    conversation_tools_supported: supported,
    auto_fetch_enabled: connector === "github",
    interval_minutes: 60,
    last_sync_at: null,
    next_sync_at: null,
    last_error_code: null,
    attempt_id: null,
    attempt_expires_at: null,
    conversation_access: connector === "github" ? "read" : "disabled",
    allowed_tool_ids: connector === "github" ? ["composio.github.search_issues"] : [],
  };
}

function clientWithConnectors(): WeatherFlowClient {
  return {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true,
      telemetry_upload: false,
      workspace_id: "w1",
      installed_packs: [],
      providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {},
      model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
    connectors: vi.fn().mockResolvedValue(connectorKinds.map(connectorStatus)),
    updateConnectorConversationAccess: vi.fn().mockResolvedValue({}),
  } as unknown as WeatherFlowClient;
}

afterEach(() => vi.restoreAllMocks());

it("shows a searchable twenty-service OAuth catalog with backend-derived states", async () => {
  render(<Cockpit client={clientWithConnectors()} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  fireEvent.click(screen.getByRole("button", { name: "OAuth" }));
  expect(await screen.findByRole("heading", { name: "连接你的常用服务" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /^查看 / })).toHaveLength(20);
  expect(screen.queryByLabelText("GitHub 连接详情")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看 GitHub" })).toHaveTextContent("已连接");
  expect(screen.getByRole("button", { name: "查看 Trello" })).toHaveTextContent("需要 OAuth 应用");

  fireEvent.click(screen.getByRole("button", { name: "沟通" }));
  expect(screen.getByRole("button", { name: "查看 Slack" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看 GitHub" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "全部" }));
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索 OAuth 服务" }), { target: { value: "notion" } });
  expect(screen.getByRole("button", { name: "查看 Notion" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看 Gmail" })).not.toBeInTheDocument();
});

it("keeps mature connector controls in details and does not advertise unsupported conversation tools", async () => {
  const client = clientWithConnectors();
  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "OAuth" }));

  fireEvent.click(await screen.findByRole("button", { name: "查看 GitHub" }));
  expect(screen.getByRole("group", { name: "GitHub 对话使用权限" })).toBeInTheDocument();
  expect(screen.getByLabelText("GitHub 抓取频率")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "查看 Slack" }));
  expect(screen.getByText("连接后暂不能在对话中使用，固定工具仍在审阅中。")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Slack 对话使用权限" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Slack 抓取频率")).not.toBeInTheDocument();

  await waitFor(() => expect(client.connectors).toHaveBeenCalledWith("w1"));
});
