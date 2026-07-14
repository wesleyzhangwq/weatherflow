import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ArrowSquareOut, Brain, Check, ClockCounterClockwise, MagnifyingGlass,
  Pause, Play, Plus, ShieldCheck, Sparkle, Trash, Wrench,
} from "@phosphor-icons/react";
import type { WeatherFlowClient } from "../bridge";
import type {
  Automation, AutomationRunLink, AutomationSchedule, AutomationStatus,
  MCPPreset, ScheduleKind, SkillCatalogEntry, Workspace,
} from "../types";

type AutomationFilter = "all" | AutomationStatus;

interface AutomationDraft {
  name: string;
  prompt: string;
  kind: ScheduleKind;
  time: string;
  minute: number;
  weekday: number;
  once: string;
}

const weekdayText = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];

function newAutomationDraft(): AutomationDraft {
  const tomorrow = new Date(Date.now() + 86_400_000);
  tomorrow.setHours(9, 0, 0, 0);
  return {
    name: "",
    prompt: "",
    kind: "weekdays",
    time: "09:00",
    minute: 0,
    weekday: 0,
    once: localDateTimeValue(tomorrow),
  };
}

function draftForAutomation(item: Automation): AutomationDraft {
  return {
    name: item.name,
    prompt: item.prompt,
    kind: item.schedule.kind,
    time: (item.schedule.at_time ?? "09:00").slice(0, 5),
    minute: item.schedule.minute ?? 0,
    weekday: item.schedule.weekday ?? 0,
    once: item.schedule.once_at ? localDateTimeValue(new Date(item.schedule.once_at)) : newAutomationDraft().once,
  };
}

function scheduleFromDraft(draft: AutomationDraft): AutomationSchedule {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  if (draft.kind === "once") return { kind: "once", timezone, once_at: new Date(draft.once).toISOString() };
  if (draft.kind === "hourly") return { kind: "hourly", timezone, minute: draft.minute };
  if (draft.kind === "weekly") return { kind: "weekly", timezone, at_time: `${draft.time}:00`, weekday: draft.weekday };
  return { kind: draft.kind, timezone, at_time: `${draft.time}:00` };
}

function localDateTimeValue(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function AutomationView({ client, workspaceId, onOperation }: { client: WeatherFlowClient; workspaceId?: string | null; onOperation: (message: string) => void }) {
  const [items, setItems] = useState<Automation[]>([]);
  const [history, setHistory] = useState<AutomationRunLink[]>([]);
  const [selectedId, setSelectedId] = useState<string | "new" | null>(null);
  const [filter, setFilter] = useState<AutomationFilter>("all");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<AutomationDraft>(newAutomationDraft);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const selected = items.find((item) => item.id === selectedId) ?? null;

  const refresh = useCallback(async () => {
    if (!workspaceId || typeof (client as Partial<WeatherFlowClient>).automations !== "function") return;
    setLoading(true);
    try {
      const next = await client.automations(workspaceId);
      setItems(next);
      setSelectedId((current) => current === "new" || next.some((item) => item.id === current) ? current : next[0]?.id ?? null);
    } finally { setLoading(false); }
  }, [client, workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (selected) setDraft(draftForAutomation(selected));
  }, [selected]);
  useEffect(() => {
    if (!selected || typeof (client as Partial<WeatherFlowClient>).automationHistory !== "function") { setHistory([]); return; }
    let current = true;
    void client.automationHistory(selected.id).then((value) => { if (current) setHistory(value); });
    return () => { current = false; };
  }, [client, selected]);

  const visible = useMemo(() => items.filter((item) => {
    if (filter !== "all" && item.status !== filter) return false;
    const needle = query.trim().toLowerCase();
    return !needle || `${item.name} ${item.prompt}`.toLowerCase().includes(needle);
  }), [filter, items, query]);

  const beginCreate = () => { setSelectedId("new"); setDraft(newAutomationDraft()); setHistory([]); };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!workspaceId || !draft.name.trim() || !draft.prompt.trim() || busy) return;
    setBusy(true);
    try {
      const schedule = scheduleFromDraft(draft);
      const saved = selected
        ? await client.updateAutomation(selected.id, { expected_version: selected.version, name: draft.name.trim(), prompt: draft.prompt.trim(), schedule })
        : await client.createAutomation({ workspace_id: workspaceId, name: draft.name.trim(), prompt: draft.prompt.trim(), schedule });
      await refresh();
      setSelectedId(saved.id);
      onOperation(selected ? "自动化已更新；下一次触发仍会创建普通任务。" : "自动化已创建并在本机调度。");
    } catch { onOperation("自动化保存失败，请检查时间与内容后重试。"); }
    finally { setBusy(false); }
  };
  const changeStatus = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const next = await client.setAutomationStatus(selected.id, selected.status === "enabled" ? "pause" : "resume", selected.version);
      setItems((current) => current.map((item) => item.id === next.id ? next : item));
      onOperation(next.status === "enabled" ? "自动化已恢复。" : "自动化已暂停。");
    } finally { setBusy(false); }
  };
  const runNow = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await client.runAutomation(selected.id);
      setHistory(await client.automationHistory(selected.id));
      onOperation("已创建一个普通 WeatherFlow 任务，可在“任务”中查看。");
    } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!selected || busy || !window.confirm(`删除自动化“${selected.name}”？历史任务不会被删除。`)) return;
    setBusy(true);
    try { await client.deleteAutomation(selected.id, selected.version); setSelectedId(null); await refresh(); onOperation("自动化已删除。"); }
    finally { setBusy(false); }
  };

  return <div className="page-view automation-view">
    <header className="tool-page-bar"><div><span>工具 · 自动化</span><h1>按你的节奏自动推进</h1></div><button className="primary" onClick={beginCreate}><Plus />创建</button></header>
    <div className="automation-layout">
      <section className="automation-browser">
        <div className="segmented-tabs" aria-label="自动化筛选">{(["all", "enabled", "paused"] as const).map((value) => <button className={filter === value ? "active" : ""} key={value} onClick={() => setFilter(value)}>{value === "all" ? "全部" : value === "enabled" ? "已开启" : "已暂停"}</button>)}</div>
        <label className="tool-search"><MagnifyingGlass /><input aria-label="搜索自动化" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索自动化…" /></label>
        <div className="automation-list">
          {visible.map((item) => <button className={item.id === selectedId ? "selected" : ""} key={item.id} onClick={() => setSelectedId(item.id)}><span className={`automation-state ${item.status}`}><Play weight="fill" /></span><span><strong>{item.name}</strong><small>{scheduleLabel(item.schedule)}</small></span><i>{item.status === "enabled" ? "开启" : "暂停"}</i></button>)}
          {!loading && visible.length === 0 && <div className="tool-empty"><ClockCounterClockwise /><strong>{items.length ? "没有匹配的自动化" : "还没有自动化"}</strong><p>自动化只负责按时提交普通任务，所有权限和批准规则保持不变。</p><button onClick={beginCreate}>创建第一个自动化</button></div>}
        </div>
      </section>
      <section className="automation-detail">
        {selectedId ? <form onSubmit={save}>
          <div className="automation-detail-head"><div><span>{selected ? selected.status === "enabled" ? "已开启" : "已暂停" : "新自动化"}</span><h2>{draft.name || "未命名自动化"}</h2></div>{selected && <div className="detail-actions"><button type="button" onClick={() => void runNow()} disabled={busy}><Play />立即运行</button><button type="button" onClick={() => void changeStatus()} disabled={busy}>{selected.status === "enabled" ? <Pause /> : <Play />}{selected.status === "enabled" ? "暂停" : "恢复"}</button><button type="button" className="danger-icon" aria-label="删除自动化" onClick={() => void remove()} disabled={busy}><Trash /></button></div>}</div>
          <label>名称<input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="例如：AI 信息晨间简报" /></label>
          <label>任务说明<textarea rows={6} value={draft.prompt} onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))} placeholder="说明每次触发时，希望 WeatherFlow 完成什么…" /></label>
          <div className="automation-form-grid"><label>重复<select value={draft.kind} onChange={(event) => setDraft((current) => ({ ...current, kind: event.target.value as ScheduleKind }))}><option value="once">仅一次</option><option value="hourly">每小时</option><option value="daily">每天</option><option value="weekdays">工作日</option><option value="weekly">每周</option></select></label>{draft.kind === "once" ? <label>时间<input type="datetime-local" value={draft.once} onChange={(event) => setDraft((current) => ({ ...current, once: event.target.value }))} /></label> : draft.kind === "hourly" ? <label>分钟<input type="number" min={0} max={59} value={draft.minute} onChange={(event) => setDraft((current) => ({ ...current, minute: Number(event.target.value) }))} /></label> : <><label>时间<input type="time" value={draft.time} onChange={(event) => setDraft((current) => ({ ...current, time: event.target.value }))} /></label>{draft.kind === "weekly" && <label>日期<select value={draft.weekday} onChange={(event) => setDraft((current) => ({ ...current, weekday: Number(event.target.value) }))}>{weekdayText.map((label, index) => <option value={index} key={label}>{label}</option>)}</select></label>}</>}</div>
          <div className="automation-policy-note"><ShieldCheck /><span><strong>普通任务，不是旁路执行</strong>触发后仍会冻结模型与能力；外部写入、安装和破坏性操作照常等待批准。</span></div>
          <button className="primary save-automation" disabled={busy || !draft.name.trim() || !draft.prompt.trim()}>{busy ? "正在保存…" : selected ? "保存修改" : "创建自动化"}</button>
          {selected && <div className="automation-history"><div className="section-heading"><h3>运行历史</h3><small>{history.length} 次</small></div>{history.length ? history.map((entry) => <article key={entry.id}><span className={`history-dot ${entry.status}`} /><div><strong>{entry.trigger === "manual" ? "手动运行" : "计划运行"}</strong><small>{new Date(entry.scheduled_for).toLocaleString("zh-CN")} · {entry.status === "submitted" ? "已创建任务" : entry.status === "pending" ? "提交中" : "提交失败"}</small></div>{entry.run_id && <code>{entry.run_id.slice(0, 8)}</code>}</article>) : <p className="history-empty">还没有运行记录。</p>}</div>}
        </form> : <div className="detail-empty centered">从左侧选择一个自动化，或创建新的计划。</div>}
      </section>
    </div>
  </div>;
}

export function SkillsView({ client, workspace, onOperation }: { client: WeatherFlowClient; workspace?: Workspace | null; onOperation: (message: string) => void }) {
  const [items, setItems] = useState<SkillCatalogEntry[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "installed">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const workspaceId = workspace?.id;
  const refresh = useCallback(async () => {
    if (!workspaceId || typeof (client as Partial<WeatherFlowClient>).skills !== "function") return;
    setItems(await client.skills(workspaceId));
  }, [client, workspaceId]);
  useEffect(() => { void refresh(); }, [refresh]);
  const visible = useMemo(() => items.filter((item) => {
    if (filter === "installed" && !item.installed) return false;
    const needle = query.trim().toLowerCase();
    return !needle || `${item.id} ${item.description_zh ?? item.description} ${item.category ?? ""}`.toLowerCase().includes(needle);
  }), [filter, items, query]);
  const mutate = async (item: SkillCatalogEntry) => {
    if (!workspace || busy) return;
    setBusy(item.id);
    try {
      const latest = (await client.workspaces()).find((candidate) => candidate.id === workspace.id);
      if (latest?.version === undefined) throw new Error("workspace version unavailable");
      if (item.installed) await client.uninstallSkill(item.id, workspace.id, latest.version);
      else await client.installSkill(item.id, workspace.id, latest.version);
      await refresh();
      onOperation(item.installed ? `${item.id} 已从当前项目移除。` : `${item.id} 已安装；新的任务可以使用它。`);
    } catch { onOperation("Skill 状态更新失败；项目可能刚刚被其他操作修改，请重试。"); }
    finally { setBusy(null); }
  };
  return <div className="page-view catalog-view">
    <header className="tool-page-bar"><div><span>工具 · Skills</span><h1>为当前项目选择技能</h1><p>来自 wesley-skills 的 127 个本机技能。安装后使用不可变快照，说明不会授予权限。</p></div><span className="catalog-count">{items.filter((item) => item.installed).length} 已安装</span></header>
    <div className="catalog-toolbar"><div className="segmented-tabs"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>全部</button><button className={filter === "installed" ? "active" : ""} onClick={() => setFilter("installed")}>已安装</button></div><label className="tool-search"><MagnifyingGlass /><input aria-label="搜索 Skills" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、用途或分类…" /></label></div>
    <div className="skill-grid">{visible.map((item) => <article className={item.installed ? "installed" : ""} key={item.id}><header><span className="skill-mark"><Brain /></span><span className={`catalog-state ${item.installed ? "active" : ""}`}>{item.installed ? <><Check />已安装</> : item.validation_status === "valid" ? "可安装" : "不可用"}</span></header><small>{item.category ?? "通用技能"}</small><h2>{item.id}</h2><p>{item.description_zh ?? item.description}</p>{item.boundary_zh && <div className="skill-boundary"><ShieldCheck />{item.boundary_zh}</div>}<footer><span>{item.source}</span><button onClick={() => void mutate(item)} disabled={busy === item.id || item.validation_status !== "valid"}>{busy === item.id ? "处理中…" : item.installed ? "移除" : "安装"}</button></footer></article>)}</div>
    {visible.length === 0 && <div className="tool-empty standalone"><Sparkle /><strong>没有匹配的 Skill</strong><p>换一个关键词，或切回“全部”。</p></div>}
  </div>;
}

export function MCPServersView({ client, workspaceId, onOperation }: { client: WeatherFlowClient; workspaceId?: string | null; onOperation: (message: string) => void }) {
  const [items, setItems] = useState<MCPPreset[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    if (!workspaceId || typeof (client as Partial<WeatherFlowClient>).mcpPresets !== "function") return;
    setItems(await client.mcpPresets(workspaceId));
  }, [client, workspaceId]);
  useEffect(() => { void refresh(); }, [refresh]);
  const mutate = async (item: MCPPreset) => {
    if (!workspaceId || busy || !item.available) return;
    setBusy(item.preset_id);
    try {
      if (!item.installed) await client.installMCP(item.preset_id, workspaceId);
      else await client.setMCPEnabled(item.preset_id, workspaceId, !item.enabled);
      await refresh();
      onOperation(!item.installed ? `${item.title} 已安装，确认后可启用。` : item.enabled ? `${item.title} 已停用。` : `${item.title} 已启用，新任务可以使用它。`);
    } catch { onOperation(`${item.title} 操作失败；没有扩大任何权限。`); }
    finally { setBusy(null); }
  };
  return <div className="page-view catalog-view mcp-view">
    <header className="tool-page-bar"><div><span>工具 · MCP Server</span><h1>连接经过约束的本机工具</h1><p>只显示由 Python 固定的官方预设、版本和参数；React 不能提交任意命令或环境变量。</p></div><span className="catalog-count">{items.filter((item) => item.enabled).length} 已启用</span></header>
    <div className="mcp-grid">{items.map((item) => <article className={`${item.enabled ? "enabled" : ""} ${!item.available ? "unavailable" : ""}`} key={item.preset_id}><header><span className="mcp-mark"><Wrench /></span><span className={`catalog-state ${item.health === "healthy" ? "active" : ""}`}>{item.health === "healthy" ? "健康" : item.health === "disabled" ? "已停用" : item.health === "not_installed" ? "未安装" : "不可用"}</span></header><div className="mcp-title"><div><small>{item.publisher} · {item.version}</small><h2>{item.title}</h2></div><a href={item.source_url} target="_blank" rel="noreferrer" aria-label={`查看 ${item.title} 源码`}><ArrowSquareOut /></a></div><p>{item.description}</p><div className="capability-tags">{item.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div><div className="mcp-risk"><ShieldCheck />{item.risk_note}</div>{item.tool_ids.length > 0 && <small className="tool-count">已发现 {item.tool_ids.length} 个工具</small>}<button className={item.enabled ? "secondary" : "primary"} onClick={() => void mutate(item)} disabled={busy === item.preset_id || !item.available}>{busy === item.preset_id ? "处理中…" : !item.available ? "暂不可用" : !item.installed ? "安装" : item.enabled ? "停用" : "启用"}</button></article>)}</div>
  </div>;
}

function scheduleLabel(schedule: AutomationSchedule): string {
  if (schedule.kind === "once") return `仅一次 · ${schedule.once_at ? new Date(schedule.once_at).toLocaleString("zh-CN") : "未设置"}`;
  if (schedule.kind === "hourly") return `每小时 · ${String(schedule.minute ?? 0).padStart(2, "0")} 分`;
  if (schedule.kind === "weekdays") return `工作日 · ${(schedule.at_time ?? "09:00").slice(0, 5)}`;
  if (schedule.kind === "weekly") return `每周${weekdayText[schedule.weekday ?? 0]} · ${(schedule.at_time ?? "09:00").slice(0, 5)}`;
  return `每天 · ${(schedule.at_time ?? "09:00").slice(0, 5)}`;
}
