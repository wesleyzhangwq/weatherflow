import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "../bridge";
import { nativeCredentials } from "../native";
import type { DesktopSnapshot, Run } from "../types";
import { Cockpit } from "./Cockpit";

const snapshot: DesktopSnapshot = {
  rhythm: { snapshot: { id: "s1", summary: "Steady rhythm", valid_until: "2026-07-12" }, policy: { proactivity: "silent", work_mode: "normal" }, weather: { scene: "fair", intensity: .5, transition: "steady", snapshot_id: "s1", valid_until: "2026-07-12", presentation_version: "v1" } },
  latest_run: { id: "r1", workspace_id: "w1", user_intent: "Ship release", status: "waiting_approval", result_summary: null, updated_at: "2026-07-12" },
  workspace: { id: "w1", name: "Project", action_roots: ["/tmp/project"], installed_packs: ["developer"] },
  metadata_sensor_enabled: false,
};

const rhythmInsights = {
  current: snapshot.rhythm,
  recent_behaviors: [{
    id: "behavior-1", kind: "activity" as const, observed_at: "2026-07-13T09:30:00Z",
    active_minutes: 48, idle_minutes: 12, app_switch_count: 7,
    dominant_category: "development", outcome: null, duration_minutes: null, step_count: null,
  }],
  profile: [{
    id: "profile-1", claim: "上午更适合完成需要持续专注的工作。", confidence: 0.84,
    origin: "derived" as const, evidence_count: 5, updated_at: "2026-07-13T09:30:00Z",
  }],
};

it("uses status weather as a read-only state, behavior, and profile view", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
    rhythmInsights: vi.fn().mockResolvedValue(rhythmInsights),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "状态天气" }));

  expect(await screen.findByRole("heading", { name: "当前状态" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "近期行为" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "长期画像" })).toBeInTheDocument();
  expect(screen.getByText("上午更适合完成需要持续专注的工作。")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "状态签到" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "主动签到" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存状态" })).not.toBeInTheDocument();
});

it("groups user-managed agent facilities under the Tools navigation", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    modelProviders: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  expect(screen.getByText("工具")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "自动化" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Skills" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "MCP Server" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "LLM 模型" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "OAuth" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "连接" })).not.toBeInTheDocument();
});

it("shows explicit operational detail and handles approval", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([{ id: "a1", action_id: "x1", run_id: "r1", status: "pending", version: 0 }]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
    timeline: vi.fn().mockResolvedValue([{ id: "e1", type: "run.created", recorded_at: "2026-07-12", payload: {} }]),
    artifacts: vi.fn().mockResolvedValue([{ id: "f1", run_id: "r1", name: "release.md", media_type: "text/markdown", digest: "d", size_bytes: 12 }]),
    decide: vi.fn().mockResolvedValue({}),
    status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: ["developer"], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: { raw_behavior: "72h", aggregate_behavior: "90d", memory: "until_explicit_reset" } }),
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 3 }),
    reset: vi.fn().mockResolvedValue({ category: "behavior", deleted_count: 3 }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  expect(await screen.findByText("Ship release")).toBeInTheDocument();
  expect(await screen.findByText("release.md")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "批准" }));
  await waitFor(() => expect(client.decide).toHaveBeenCalledWith("a1", "approve", 0, "w1"));
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  expect(screen.getByText("等待本机行为授权")).toBeInTheDocument();
});

it("requires review then a second explicit click before behavior reset", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]), timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: ["developer"], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: { raw_behavior: "72h", aggregate_behavior: "90d", memory: "until_explicit_reset" } }),
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 3 }),
    reset: vi.fn().mockResolvedValue({ category: "behavior", deleted_count: 3 }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  fireEvent.click(await screen.findByRole("button", { name: "检查行为数据清理" }));
  expect(client.reset).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "删除 3 条行为记录" }));
  await waitFor(() => expect(client.reset).toHaveBeenCalledWith("behavior", undefined));
});

it("lets the user switch and persist the desktop theme from Settings", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {},
      model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "设置" }));

  expect(screen.getByRole("radiogroup", { name: "界面主题" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "深色" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(screen.getByRole("radio", { name: "深色" })).toHaveAttribute("aria-checked", "true");

  fireEvent.click(screen.getByRole("radio", { name: "浅色" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});

describe("Cockpit lifecycle", () => {
  it("has no code path that opens another Cockpit from run events", async () => {
    const client = { approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]), timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]), status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {} }) } as unknown as WeatherFlowClient;
    const open = vi.fn();
    window.addEventListener("weatherflow:open_cockpit", open);
    render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
    await screen.findByText("今天想一起推进什么？");
    expect(open).not.toHaveBeenCalled();
    window.removeEventListener("weatherflow:open_cockpit", open);
  });
});

it("shows provider switches and enables a provider after one key configuration", async () => {
  const setCredential = vi.spyOn(nativeCredentials, "set").mockResolvedValue({ provider: "deepseek", key_present: true });
  const credentialStatus = vi.spyOn(nativeCredentials, "status").mockImplementation(async (provider) => ({ provider, key_present: false }));
  const configureModel = vi.fn().mockResolvedValue({});
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
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
    modelProviders: vi.fn().mockResolvedValue([
      { provider: "minimax", label: "MiniMax", base_url: "https://api.minimaxi.com/v1", default_model: "MiniMax-M3", suggested_models: ["MiniMax-M3", "MiniMax-M2.7"] },
      { provider: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-v4-flash", suggested_models: ["deepseek-v4-flash", "deepseek-v4-pro"] },
      { provider: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", default_model: "gpt-5.6-terra", suggested_models: ["gpt-5.6-terra"] },
      { provider: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com/v1", default_model: "claude-sonnet-5", suggested_models: ["claude-sonnet-5"] },
    ]),
    providerModels: vi.fn().mockResolvedValue({ provider: "deepseek", models: [{ id: "deepseek-v4-flash", selectable: true, compatibility: "agent_ready", note: null }, { id: "deepseek-v4-pro", selectable: true, compatibility: "agent_ready", note: null }], source: "provider" }),
    configureModel,
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 0 }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "LLM 模型" }));
  const deepseek = await screen.findByRole("switch", { name: "DeepSeek" });
  expect(screen.getByRole("switch", { name: "OpenAI" })).toHaveAttribute("aria-checked", "false");
  expect(screen.getByRole("switch", { name: "Anthropic" })).toHaveAttribute("aria-checked", "false");
  expect(deepseek).toHaveAttribute("aria-checked", "false");
  fireEvent.click(deepseek);

  fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "验证并启用 DeepSeek" }));

  await waitFor(() => expect(configureModel).toHaveBeenCalledWith({
    provider: "deepseek",
    model: "deepseek-v4-flash",
    base_url: "https://api.deepseek.com",
  }, "w1"));
  expect(deepseek).toHaveAttribute("aria-checked", "true");
  expect(setCredential).toHaveBeenCalledWith("deepseek", "secret");
  setCredential.mockRestore();
  credentialStatus.mockRestore();
});

it("lets the user switch the active conversation model without entering the key again", async () => {
  const setCredential = vi.spyOn(nativeCredentials, "set");
  const credentialStatus = vi.spyOn(nativeCredentials, "status").mockImplementation(async (provider) => ({
    provider,
    key_present: provider === "minimax" || provider === "deepseek",
  }));
  const configureModel = vi.fn().mockResolvedValue({});
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
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
      model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
    modelProviders: vi.fn().mockResolvedValue([
      { provider: "minimax", label: "MiniMax", base_url: "https://api.minimaxi.com/v1", default_model: "MiniMax-M3", suggested_models: ["MiniMax-M3", "MiniMax-M2.7"] },
      { provider: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-v4-flash", suggested_models: ["deepseek-v4-flash", "deepseek-v4-pro"] },
    ]),
    providerModels: vi.fn().mockResolvedValue({ provider: "deepseek", models: [{ id: "deepseek-v4-flash", selectable: true, compatibility: "agent_ready", note: null }, { id: "deepseek-v4-pro", selectable: true, compatibility: "agent_ready", note: null }], source: "provider" }),
    configureModel,
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(await screen.findByRole("button", { name: "当前模型：MiniMax · MiniMax-M3" }));
  fireEvent.click(await screen.findByRole("button", { name: "选择 DeepSeek" }));
  fireEvent.click(await screen.findByRole("button", { name: "使用 deepseek-v4-pro" }));

  await waitFor(() => expect(configureModel).toHaveBeenCalledWith({
    provider: "deepseek",
    model: "deepseek-v4-pro",
    base_url: "https://api.deepseek.com",
  }, "w1"));
  expect(setCredential).not.toHaveBeenCalled();
  setCredential.mockRestore();
  credentialStatus.mockRestore();
});

it("allows MiniMax M2 models backed by encrypted provider continuations", async () => {
  const credentialStatus = vi.spyOn(nativeCredentials, "status").mockImplementation(async (provider) => ({
    provider,
    key_present: provider === "minimax",
  }));
  const configureModel = vi.fn().mockResolvedValue({});
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
    modelProviders: vi.fn().mockResolvedValue([
      { provider: "minimax", label: "MiniMax", base_url: "https://api.minimaxi.com/v1", default_model: "MiniMax-M3", suggested_models: ["MiniMax-M3", "MiniMax-M2.7"] },
    ]),
    providerModels: vi.fn().mockResolvedValue({
      provider: "minimax",
      source: "provider",
      models: [
        { id: "MiniMax-M3", selectable: true, compatibility: "agent_ready", note: null },
        { id: "MiniMax-M2.7", selectable: true, compatibility: "agent_ready", note: null },
      ],
    }),
    configureModel,
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 0 }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "LLM 模型" }));

  const m27 = await screen.findByRole("button", { name: "使用 MiniMax-M2.7" });
  expect(m27).toBeEnabled();
  fireEvent.click(m27);
  await waitFor(() => expect(configureModel).toHaveBeenCalledWith(
    { provider: "minimax", model: "MiniMax-M2.7", base_url: "https://api.minimaxi.com/v1" },
    "w1",
  ));
  credentialStatus.mockRestore();
});

it("configures the OAuth broker and exposes backend-approved connectors", async () => {
  const setCredential = vi.spyOn(nativeCredentials, "set").mockResolvedValue({ provider: "composio", key_present: true });
  const configureConnectors = vi.fn().mockResolvedValue({ configured: true });
  const connectConnector = vi.fn().mockResolvedValue({
    attempt_id: "attempt-1",
    connect_url: "https://connect.composio.dev/link/opaque",
    expires_at: "2026-07-13T12:00:00Z",
  });
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
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
    connectors: vi.fn()
      .mockResolvedValueOnce([
        { connector: "github", label: "GitHub", phase: null, configured: false, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
        { connector: "gmail", label: "Gmail", phase: null, configured: false, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
        { connector: "google_calendar", label: "Google Calendar", phase: null, configured: false, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
      ])
      .mockResolvedValue([
        { connector: "github", label: "GitHub", phase: null, configured: true, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
        { connector: "gmail", label: "Gmail", phase: null, configured: true, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
        { connector: "google_calendar", label: "Google Calendar", phase: null, configured: true, connected: false, auto_fetch_enabled: false, interval_minutes: 60 },
      ]),
    configureConnectors,
    connectConnector,
  } as unknown as WeatherFlowClient;

  const opened = vi.fn();
  window.addEventListener("weatherflow:open_connector_url", opened);
  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "OAuth" }));

  expect(await screen.findByText("连接你的常用服务")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看 GitHub" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看 Gmail" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看 Google Calendar" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看 Slack" })).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Composio Project API Key"), { target: { value: "cmp_live_secret" } });
  fireEvent.click(screen.getByRole("button", { name: "验证并保存连接密钥" }));
  await waitFor(() => expect(configureConnectors).toHaveBeenCalledWith());
  expect(setCredential).toHaveBeenCalledWith("composio", "cmp_live_secret");

  fireEvent.click(await screen.findByRole("button", { name: "查看 GitHub" }));
  fireEvent.click(screen.getByRole("button", { name: "连接 GitHub" }));
  await waitFor(() => expect(connectConnector).toHaveBeenCalledWith("github", "w1"));
  expect(opened).toHaveBeenCalled();
  window.removeEventListener("weatherflow:open_connector_url", opened);
  setCredential.mockRestore();
});

it("resumes authoritative polling for a pending connector after the view reopens", async () => {
  vi.useFakeTimers();
  const connectorAttempt = vi.fn().mockResolvedValue({
    id: "attempt-pending",
    workspace_id: "w1",
    connector: "github",
    account_id: "account-1",
    external_account_id: "ca-1",
    phase: "active",
    expires_at: "2099-07-13T12:00:00Z",
    created_at: "2026-07-13T11:55:00Z",
    updated_at: "2026-07-13T11:56:00Z",
  });
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
    connectors: vi.fn().mockResolvedValue([
      { connector: "github", label: "GitHub", phase: "waiting_user", configured: true, connected: false, display_name: null, auto_fetch_enabled: false, interval_minutes: 60, last_sync_at: null, next_sync_at: null, last_error_code: null, attempt_id: "attempt-pending", attempt_expires_at: "2099-07-13T12:00:00Z" },
      { connector: "gmail", label: "Gmail", phase: null, configured: true, connected: false, display_name: null, auto_fetch_enabled: false, interval_minutes: 60, last_sync_at: null, next_sync_at: null, last_error_code: null, attempt_id: null, attempt_expires_at: null },
      { connector: "google_calendar", label: "Google Calendar", phase: null, configured: true, connected: false, display_name: null, auto_fetch_enabled: false, interval_minutes: 60, last_sync_at: null, next_sync_at: null, last_error_code: null, attempt_id: null, attempt_expires_at: null },
    ]),
    connectorAttempt,
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "OAuth" }));
  await act(async () => { await Promise.resolve(); });
  fireEvent.click(screen.getByRole("button", { name: "查看 GitHub" }));
  expect(screen.getByRole("button", { name: "连接 GitHub" })).toBeDisabled();
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  expect(connectorAttempt).toHaveBeenCalledWith("attempt-pending");
  vi.useRealTimers();
});

it("lets the user explicitly grant connector tools to conversations", async () => {
  const updateConnectorConversationAccess = vi.fn().mockResolvedValue({});
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
    connectors: vi.fn().mockResolvedValue([
      {
        connector: "github", label: "GitHub", phase: "active", configured: true, connected: true,
        display_name: "wesz", auto_fetch_enabled: true, interval_minutes: 60, last_sync_at: null,
        next_sync_at: null, last_error_code: null, attempt_id: null, attempt_expires_at: null,
        conversation_access: "read", allowed_tool_ids: ["composio.github.search_issues"],
      },
      {
        connector: "gmail", label: "Gmail", phase: null, configured: true, connected: false,
        display_name: null, auto_fetch_enabled: false, interval_minutes: 60, last_sync_at: null,
        next_sync_at: null, last_error_code: null, attempt_id: null, attempt_expires_at: null,
        conversation_access: "disabled", allowed_tool_ids: [],
      },
      {
        connector: "google_calendar", label: "Google Calendar", phase: null, configured: true, connected: false,
        display_name: null, auto_fetch_enabled: false, interval_minutes: 60, last_sync_at: null,
        next_sync_at: null, last_error_code: null, attempt_id: null, attempt_expires_at: null,
        conversation_access: "disabled", allowed_tool_ids: [],
      },
    ]),
    updateConnectorConversationAccess,
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "OAuth" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看 GitHub" }));

  expect(await screen.findByRole("group", { name: "GitHub 对话使用权限" })).toBeInTheDocument();
  expect(screen.getByText("执行前逐次向你确认。", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("已允许 1 个固定工具")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "读取并提议操作" }));

  await waitFor(() => expect(updateConnectorConversationAccess).toHaveBeenCalledWith("github", "read_write", "w1"));
});

it("keeps human weather separate from the current agent task in the conversation header", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  expect(await screen.findByLabelText("人的状态天气")).toHaveTextContent("微晴 · 稳定");
  expect(screen.getByLabelText("智能体任务状态")).toHaveTextContent("等待批准");
});

it("shows searchable pinned and recent sessions and selects each latest run", async () => {
  const firstRun = { ...snapshot.latest_run!, id: "run-first", session_id: "session-first", user_intent: "整理发布计划", status: "succeeded" as const };
  const pinnedRun = { ...snapshot.latest_run!, id: "run-pinned", session_id: "session-pinned", user_intent: "检查今天邮件", status: "succeeded" as const, updated_at: "2026-07-14T02:00:00Z" };
  const pinnedEarlierRun = { ...snapshot.latest_run!, id: "run-pinned-earlier", session_id: "session-pinned", user_intent: "整理昨天邮件", status: "succeeded" as const, updated_at: "2026-07-14T01:00:00Z" };
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([pinnedRun, pinnedEarlierRun, firstRun]),
    sessions: vi.fn().mockResolvedValue([
      { id: "session-first", workspace_id: "w1", title: "发布计划", pinned: false, latest_run_id: "run-first", created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T02:00:00Z" },
      { id: "session-pinned", workspace_id: "w1", title: "每日简报", pinned: true, latest_run_id: "run-pinned", created_at: "2026-07-13T01:00:00Z", updated_at: "2026-07-13T02:00:00Z" },
    ]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {},
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  expect(await screen.findByRole("button", { name: "打开会话：每日简报" })).toHaveAttribute("aria-current", "true");
  expect(screen.getByText("检查今天邮件")).toBeInTheDocument();
  expect(screen.getByText("整理昨天邮件")).toBeInTheDocument();
  expect(screen.queryByText("整理发布计划")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "任务" }));
  fireEvent.click(screen.getByRole("button", { name: "整理发布计划，已完成" }));
  fireEvent.click(screen.getByRole("button", { name: "对话" }));
  expect(screen.getByRole("button", { name: "打开会话：发布计划" })).toHaveAttribute("aria-current", "true");

  fireEvent.change(screen.getByRole("searchbox", { name: "搜索对话" }), { target: { value: "发布" } });
  expect(screen.queryByRole("button", { name: "打开会话：每日简报" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "打开会话：发布计划" }));
  expect(await screen.findByText("整理发布计划")).toBeInTheDocument();
});

it("persists an automatic title after the first message in a new session", async () => {
  const session = { id: "session-new", workspace_id: "w1", title: "新对话", pinned: false, latest_run_id: null, created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T01:00:00Z" };
  const accepted = { ...snapshot.latest_run!, id: "run-new", session_id: "session-new", user_intent: "帮我复盘这周项目", status: "queued" as const };
  const updateSession = vi.fn().mockResolvedValue({ ...session, title: "帮我复盘这周项目", latest_run_id: "run-new" });
  const createRun = vi.fn().mockResolvedValue(accepted);
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]), sessions: vi.fn().mockResolvedValue([session]),
    updateSession, createRun,
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {},
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  expect(await screen.findByRole("button", { name: "打开会话：新对话" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "帮我复盘这周项目" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(updateSession).toHaveBeenCalledWith("session-new", "w1", { title: "帮我复盘这周项目" }));
  expect(await screen.findByRole("button", { name: "打开会话：帮我复盘这周项目" })).toBeInTheDocument();
});

it("creates, renames, pins, and sends from a durable session", async () => {
  const session = { id: "session-new", workspace_id: "w1", title: "新对话", pinned: false, latest_run_id: null, created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T01:00:00Z" };
  const renamed = { ...session, title: "项目复盘" };
  const pinned = { ...renamed, pinned: true };
  const accepted = { ...snapshot.latest_run!, id: "run-new", user_intent: "复盘这周项目", status: "queued" as const };
  const createSession = vi.fn().mockResolvedValue(session);
  const updateSession = vi.fn()
    .mockResolvedValueOnce(renamed)
    .mockResolvedValueOnce(pinned);
  const createRun = vi.fn().mockResolvedValue(accepted);
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]), sessions: vi.fn().mockResolvedValue([]),
    createSession, updateSession, createRun,
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {},
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(await screen.findByRole("button", { name: "新对话" }));
  await waitFor(() => expect(createSession).toHaveBeenCalledWith("w1"));
  expect(screen.getByText("说出你真正想完成的事")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "会话选项：新对话" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
  fireEvent.change(screen.getByRole("textbox", { name: "重命名会话" }), { target: { value: "项目复盘" } });
  fireEvent.keyDown(screen.getByRole("textbox", { name: "重命名会话" }), { key: "Enter" });
  await waitFor(() => expect(updateSession).toHaveBeenCalledWith("session-new", "w1", { title: "项目复盘" }));

  fireEvent.click(screen.getByRole("button", { name: "会话选项：项目复盘" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "置顶" }));
  await waitFor(() => expect(updateSession).toHaveBeenCalledWith("session-new", "w1", { pinned: true }));

  fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "复盘这周项目" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(createRun).toHaveBeenCalledWith("复盘这周项目", expect.any(String), "w1", null, "session-new"));
});

it("requires a second explicit action before permanently deleting a conversation", async () => {
  const doomed = { id: "session-old", workspace_id: "w1", title: "旧对话", pinned: false, latest_run_id: "run-old", version: 0, created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T02:00:00Z" };
  const remaining = { id: "session-next", workspace_id: "w1", title: "保留对话", pinned: false, latest_run_id: "run-next", version: 0, created_at: "2026-07-13T01:00:00Z", updated_at: "2026-07-13T02:00:00Z" };
  const runs = [
    { ...snapshot.latest_run!, id: "run-old", session_id: doomed.id, user_intent: "删除我", status: "succeeded" as const },
    { ...snapshot.latest_run!, id: "run-next", session_id: remaining.id, user_intent: "留下我", status: "succeeded" as const },
  ];
  const deleteSession = vi.fn().mockResolvedValue(undefined);
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue(runs), sessions: vi.fn().mockResolvedValue([doomed, remaining]),
    deleteSession, timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {},
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(await screen.findByRole("button", { name: "会话选项：旧对话" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "删除对话" }));

  expect(deleteSession).not.toHaveBeenCalled();
  expect(screen.getByText("这个对话及其任务记录会从本机永久删除。")) .toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "永久删除旧对话" }));

  await waitFor(() => expect(deleteSession).toHaveBeenCalledWith("session-old", "w1"));
  expect(screen.queryByRole("button", { name: "打开会话：旧对话" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开会话：保留对话" })).toHaveAttribute("aria-current", "true");
});

it("explains why sending is unavailable until a workspace is selected", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: false, provider: "minimax", model: null, base_url: null, credential_available: false },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "帮我整理今天的工作" } });

  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(screen.getByText("先选择或添加一个项目，才能开始任务")).toBeInTheDocument();
});

it("renders long task intents as bounded navigation summaries", async () => {
  const longIntent = "请完整检查这个非常长的项目任务，并在不改变用户目标的前提下整理风险、执行记录、批准项以及最终产出，确保任务列表不会覆盖详情区域";
  const longRun = { ...snapshot.latest_run, id: "long-run", user_intent: longIntent, status: "running" as const };
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([longRun]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: "任务" }));

  const taskNavigation = await screen.findByLabelText("任务列表");
  expect(taskNavigation).toBeInTheDocument();
  expect(screen.getByRole("button", { name: `${longIntent}，执行中` })).toHaveAttribute("aria-pressed", "true");
});

it("does not submit the chat composer while a Chinese input method is composing", async () => {
  const createRun = vi.fn().mockResolvedValue({ id: "new-run" });
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    createRun,
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  const input = screen.getByLabelText("对话输入");

  fireEvent.compositionStart(input);
  fireEvent.change(input, { target: { value: "你好" } });
  fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 229, isComposing: true });

  await Promise.resolve();
  expect(createRun).not.toHaveBeenCalled();

  fireEvent.compositionEnd(input);
  fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
  await waitFor(() => expect(createRun).toHaveBeenCalledOnce());
});

it("follows a newly accepted conversation until its answer arrives without another click", async () => {
  const previousRun = {
    ...snapshot.latest_run!,
    id: "previous-run",
    status: "succeeded" as const,
    result_summary: "上一条回复",
  };
  const queuedRun = {
    ...snapshot.latest_run!,
    id: "new-run",
    user_intent: "继续处理这个问题",
    status: "queued" as const,
    result_summary: null,
    updated_at: "2026-07-13T12:00:00Z",
  };
  const completedRun = {
    ...queuedRun,
    status: "succeeded" as const,
    result_summary: "这是自动出现的最终回复",
    updated_at: "2026-07-13T12:00:01Z",
  };
  let recentRuns: Run[] = [previousRun];
  const client = {
    approvals: vi.fn().mockResolvedValue([]),
    runs: vi.fn().mockImplementation(async () => recentRuns),
    timeline: vi.fn().mockResolvedValue([]),
    artifacts: vi.fn().mockResolvedValue([]),
    createRun: vi.fn().mockImplementation(async () => {
      recentRuns = [queuedRun, previousRun];
      return queuedRun;
    }),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: true },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);
  expect(await screen.findByText("上一条回复")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "继续处理这个问题" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  const newConversation = await screen.findByRole("button", { name: "查看任务：继续处理这个问题" });
  expect(newConversation.closest("article")).toHaveClass("selected");

  recentRuns = [completedRun, previousRun];
  expect(await screen.findByText("这是自动出现的最终回复", {}, { timeout: 1500 })).toBeInTheDocument();
});

it("turns a keychain failure into an actionable model recovery message", async () => {
  const failedRun = {
    ...snapshot.latest_run,
    id: "failed-keychain",
    status: "failed" as const,
    error_class: "KeyringError",
    error_message: "background execution failed",
  };
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([failedRun]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: false },
    }),
  } as unknown as WeatherFlowClient;

  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  expect(await screen.findByText("无法读取模型密钥，请到“LLM 模型”重新粘贴 API Key。")) .toBeInTheDocument();
});

it("explains how to recover when the configured model credential is unavailable", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    modelProviders: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({
      local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {},
      behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true },
      retention: {}, model: { configured: true, provider: "minimax", model: "MiniMax-M3", base_url: "https://api.minimaxi.com/v1", credential_available: false },
    }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} selectedWorkspaceId="w1" />);

  fireEvent.click(screen.getByRole("button", { name: "LLM 模型" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "WeatherFlow 会直接通过系统安全存储处理，不需要你打开“钥匙串访问”",
  );
});
