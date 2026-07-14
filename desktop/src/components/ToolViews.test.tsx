import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WeatherFlowClient } from "../bridge";
import type { Automation, MCPPreset, SkillCatalogEntry, Workspace } from "../types";
import { AutomationView, MCPServersView, SkillsView } from "./ToolViews";

const workspace: Workspace = {
  id: "w1", name: "Project", action_roots: ["/tmp/project"],
  installed_packs: ["developer"], installed_skills: [], version: 3,
};

describe("Automation tools", () => {
  it("creates a schedule that will submit a normal Run", async () => {
    const created: Automation = {
      id: "a1", workspace_id: "w1", name: "每日简报", prompt: "整理三个重点",
      schedule: { kind: "weekdays", timezone: "Asia/Shanghai", at_time: "09:00:00" },
      status: "enabled", next_run_at: "2026-07-15T01:00:00Z", last_run_at: null,
      version: 0, created_at: "2026-07-14T00:00:00Z", updated_at: "2026-07-14T00:00:00Z",
    };
    const createAutomation = vi.fn().mockResolvedValue(created);
    const client = {
      automations: vi.fn().mockResolvedValue([]), createAutomation,
      automationHistory: vi.fn().mockResolvedValue([]),
    } as unknown as WeatherFlowClient;
    render(<AutomationView client={client} workspaceId="w1" onOperation={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "每日简报" } });
    fireEvent.change(screen.getByLabelText("任务说明"), { target: { value: "整理三个重点" } });
    fireEvent.click(screen.getByRole("button", { name: "创建自动化" }));

    await waitFor(() => expect(createAutomation).toHaveBeenCalledWith(expect.objectContaining({
      workspace_id: "w1", name: "每日简报", prompt: "整理三个重点",
      schedule: expect.objectContaining({ kind: "weekdays" }),
    })));
  });
});

describe("Skill catalog", () => {
  it("installs a validated skill against the latest Workspace version", async () => {
    const skill: SkillCatalogEntry = {
      id: "focus-coach", name: "focus-coach", description: "Focus", description_zh: "安排专注时段",
      boundary_zh: "不会改变用户目标", category: "效率", license: null, related: [], reads: [],
      source: "wesley-skills", source_path: "/catalog/focus-coach", source_digest: "a".repeat(64),
      validation_status: "valid", validation_errors: [], installed: false, installed_reference: null,
    };
    const request = { status: "needs_approval" as const, action_id: "act1", approval_id: "ap1", approval_version: 0, run_id: "r1", preview: {} };
    const installSkill = vi.fn().mockResolvedValue(request);
    const decide = vi.fn().mockResolvedValue({});
    const client = {
      skills: vi.fn().mockResolvedValue([skill]), workspaces: vi.fn().mockResolvedValue([workspace]), installSkill, decide,
    } as unknown as WeatherFlowClient;
    render(<SkillsView client={client} workspace={workspace} onOperation={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "安装" }));
    await waitFor(() => expect(installSkill).toHaveBeenCalledWith("focus-coach", "w1", 3, expect.any(String)));
    expect(screen.getByText("需要批准")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准安装" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap1", "approve", 0, "w1"));
  });
});

describe("MCP catalog", () => {
  it("shows unavailable presets and installs only a fixed catalog id", async () => {
    const presets: MCPPreset[] = [{
      preset_id: "filesystem", title: "本地文件", description: "只访问项目目录", publisher: "MCP",
      source_url: "https://github.com/modelcontextprotocol/servers", version: "2026.7.10",
      capabilities: ["文件读取"], risk_note: "写入仍需批准", available: true,
      unavailable_reason: null, installed: false, enabled: false, health: "not_installed",
      tool_ids: [], installed_at: null, checked_at: null,
    }, {
      preset_id: "fetch", title: "网页抓取", description: "抓取网页", publisher: "MCP",
      source_url: "https://github.com/modelcontextprotocol/servers", version: "2026.7.10",
      capabilities: ["网页抓取"], risk_note: "当前缺少 SSRF 边界", available: false,
      unavailable_reason: "private network", installed: false, enabled: false, health: "not_installed",
      tool_ids: [], installed_at: null, checked_at: null,
    }];
    const request = { status: "needs_approval" as const, action_id: "act2", approval_id: "ap2", approval_version: 0, run_id: "r2", preview: {} };
    const installMCP = vi.fn().mockResolvedValue(request);
    const decide = vi.fn().mockResolvedValue({});
    const client = { mcpPresets: vi.fn().mockResolvedValue(presets), installMCP, decide } as unknown as WeatherFlowClient;
    render(<MCPServersView client={client} workspaceId="w1" onOperation={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "暂不可用" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "安装" }));
    await waitFor(() => expect(installMCP).toHaveBeenCalledWith("filesystem", "w1", expect.any(String)));
    fireEvent.click(screen.getByRole("button", { name: "批准安装" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap2", "approve", 0, "w1"));
  });
});
