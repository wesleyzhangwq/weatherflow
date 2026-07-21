import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Brain, CaretDown, ChatCircleDots, Check, CheckCircle, ClockCounterClockwise, Cloud, CloudSun,
  Desktop, DotsThree, Eye, FolderOpen, GearSix, ListChecks, ListDashes, MagnifyingGlass, MicrosoftOutlookLogo,
  MicrosoftTeamsLogo, Moon, Paperclip, PaperPlaneRight, PencilSimple, PlugsConnected, Plus, Pulse, PushPin,
  Robot, ShieldCheck, SlackLogo, Sun, Trash, WarningCircle, Waves, Wrench,
} from "@phosphor-icons/react";
import {
  SiAirtable, SiAsana, SiClickup, SiConfluence, SiDiscord, SiDropbox, SiGithub, SiGitlab, SiGmail,
  SiGooglecalendar, SiGoogledrive, SiGooglesheets, SiJira, SiLinear, SiNotion, SiTrello,
} from "@icons-pack/react-simple-icons";
import { WeatherFlowBridgeError, WeatherFlowClient } from "../bridge";
import { nativeCredentials, nativeWindows, type CredentialProvider } from "../native";
import { getThemePreference, setThemePreference, type ThemePreference } from "../theme";
import { AutomationView, MCPServersView, SkillsView } from "./ToolViews";
import { WatchView } from "./WatchView";
import type {
  BillingOrigin,
  ActivitySummarySettings, Approval, Artifact, ConnectionAttempt, ConnectorKind, ConnectorStatus, DesktopSnapshot,
  LedgerEvent, ModelProviderPreset, ProviderModel, ResetPreview, Run, RunUsage, Session, SystemStatus, ToolMode, Workspace,
} from "../types";

type ViewId = "chat" | "runs" | "watch" | "automations" | "skills" | "mcp" | "models" | "oauth" | "settings";

const runStatusText: Record<Run["status"], string> = {
  queued: "已排队", planning: "规划中", running: "执行中", waiting_approval: "等待批准",
  waiting_user: "等待你的输入", paused: "已暂停", needs_review: "需要检查",
  succeeded: "已完成", failed: "失败", cancelled: "已取消",
};
function compareSessions(left: Session, right: Session): number {
  if (left.pinned !== right.pinned) return left.pinned ? -1 : 1;
  return Date.parse(right.updated_at) - Date.parse(left.updated_at);
}
function conversationTitle(intent: string): string {
  const compact = intent.replace(/\s+/g, " ").trim();
  return compact.length > 24 ? `${compact.slice(0, 24)}…` : compact;
}
const weatherText = { clear: "晴朗 · 心流", fair: "微晴 · 稳定", fog: "薄雾 · 分散", storm: "风暴 · 过载", still: "静滞 · 受阻", night: "夜色 · 恢复", mixed: "混合 · 待确认" } as const;
function presetModelOptions(provider: ModelProviderPreset): ProviderModel[] {
  return provider.suggested_models.map((id) => ({
    id, selectable: true, compatibility: "agent_ready", note: null,
  }));
}

function billingOriginLabel(origin: BillingOrigin): string {
  const labels: Record<BillingOrigin, string> = {
    minimax_global_paygo: "国际站 · 按量计费（USD）",
    minimax_cn_paygo: "中国站 · 按量计费（CNY）",
    minimax_global_token_plan: "国际站 · Token Plan（金额 unknown）",
    minimax_cn_token_plan: "中国站 · Token Plan（金额 unknown）",
  };
  return labels[origin];
}

async function loadRunUsage(client: WeatherFlowClient, runId: string): Promise<RunUsage | null> {
  const method = (client as Partial<WeatherFlowClient>).runUsage;
  if (typeof method !== "function") return null;
  try {
    return await method.call(client, runId);
  } catch {
    return null;
  }
}

interface CockpitProps {
  client: WeatherFlowClient;
  snapshot: DesktopSnapshot | null;
  offline: boolean;
  workspaces?: Workspace[];
  selectedWorkspaceId?: string | null;
  onSelectWorkspace?: (workspaceId: string) => void;
  onAuthorizeWorkspace?: (path: string) => Promise<Workspace>;
}

export function Cockpit({ client, snapshot, offline, workspaces = [], selectedWorkspaceId, onSelectWorkspace, onAuthorizeWorkspace }: CockpitProps) {
  const [view, setView] = useState<ViewId>("chat");
  const [runs, setRuns] = useState<Run[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const refreshGeneration = useRef(0);
  const sessionRefreshGeneration = useRef(0);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [timeline, setTimeline] = useState<LedgerEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [usage, setUsage] = useState<RunUsage | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [providers, setProviders] = useState<ModelProviderPreset[]>([]);
  const [resetPreview, setResetPreview] = useState<ResetPreview | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [toolMode, setToolMode] = useState<ToolMode>("ask");
  const sessionsEnabled = Boolean(selectedWorkspaceId) && typeof (client as Partial<WeatherFlowClient>).sessions === "function";
  const activeSession = useMemo(() => sessions.find((item) => item.id === selectedSessionId) ?? null, [selectedSessionId, sessions]);
  const activeSessionRunId = useMemo(() => {
    if (!sessionsEnabled || !activeSession) return null;
    const selected = runs.find((item) => item.id === selectedRunId);
    if (selected && (selected.session_id === activeSession.id || (!selected.session_id && selected.id === activeSession.latest_run_id))) {
      return selected.id;
    }
    return activeSession.latest_run_id;
  }, [activeSession, runs, selectedRunId, sessionsEnabled]);
  const run = useMemo(() => {
    if (sessionsEnabled) return activeSessionRunId ? runs.find((item) => item.id === activeSessionRunId) ?? null : null;
    return runs.find((item) => item.id === selectedRunId) ?? runs[0] ?? snapshot?.latest_run ?? null;
  }, [activeSessionRunId, runs, selectedRunId, sessionsEnabled, snapshot]);
  const selectedWorkspace = workspaces.find((item) => item.id === selectedWorkspaceId)
    ?? (snapshot && snapshot.workspace.id === selectedWorkspaceId ? snapshot.workspace : null);
  const pending = approvals.filter((item) => item.status === "pending");

  const refresh = useCallback(async (preferredRunId?: string | null) => {
    const generation = refreshGeneration.current + 1;
    refreshGeneration.current = generation;
    const [nextApprovals, status, recent] = await Promise.all([
      client.approvals(), client.status(selectedWorkspaceId), client.runs(selectedWorkspaceId),
    ]);
    if (generation !== refreshGeneration.current) return;
    setRuns(recent);
    setApprovals(nextApprovals.filter((approval) => recent.some((item) => item.id === approval.run_id)));
    setSystem(status);
    const requestedRunId = preferredRunId ?? selectedRunIdRef.current;
    const activeId = requestedRunId && recent.some((item) => item.id === requestedRunId) ? requestedRunId : recent[0]?.id;
    selectedRunIdRef.current = activeId ?? null;
    setSelectedRunId(activeId ?? null);
    if (activeId) {
      const [events, files, nextUsage] = await Promise.all([
        client.timeline(activeId), client.artifacts(activeId), loadRunUsage(client, activeId),
      ]);
      if (generation !== refreshGeneration.current) return;
      setTimeline(events); setArtifacts(files); setUsage(nextUsage);
    } else { setTimeline([]); setArtifacts([]); setUsage(null); }
  }, [client, selectedWorkspaceId]);

  const refreshSessions = useCallback(async (preferredSessionId?: string | null) => {
    const generation = sessionRefreshGeneration.current + 1;
    sessionRefreshGeneration.current = generation;
    if (!selectedWorkspaceId || typeof (client as Partial<WeatherFlowClient>).sessions !== "function") {
      if (generation === sessionRefreshGeneration.current) {
        setSessions([]); setSelectedSessionId(null);
      }
      return;
    }
    let next: Session[];
    try {
      next = await client.sessions(selectedWorkspaceId);
    } catch {
      return;
    }
    if (generation !== sessionRefreshGeneration.current) return;
    setSessions(next);
    setSelectedSessionId((current) => {
      const requested = preferredSessionId ?? current;
      if (requested && next.some((item) => item.id === requested)) return requested;
      return [...next].sort(compareSessions)[0]?.id ?? null;
    });
  }, [client, selectedWorkspaceId]);

  useEffect(() => {
    refreshGeneration.current += 1;
    sessionRefreshGeneration.current += 1;
    setRuns([]);
    setSessions([]);
    setSelectedSessionId(null);
    selectedRunIdRef.current = null;
    setSelectedRunId(null);
    setApprovals([]);
    setTimeline([]);
    setArtifacts([]);
    setUsage(null);
  }, [selectedWorkspaceId]);
  useEffect(() => { void refresh(); }, [refresh, snapshot]);
  useEffect(() => { void refreshSessions(); }, [refreshSessions, snapshot]);
  useEffect(() => {
    if (!sessionsEnabled) return;
    const runId = activeSessionRunId;
    selectedRunIdRef.current = runId;
    setSelectedRunId((current) => current === runId ? current : runId);
    if (!runId) { setTimeline([]); setArtifacts([]); setUsage(null); return; }
    let current = true;
    void Promise.all([client.timeline(runId), client.artifacts(runId), loadRunUsage(client, runId)]).then(([events, files, nextUsage]) => {
      if (current) { setTimeline(events); setArtifacts(files); setUsage(nextUsage); }
    });
    return () => { current = false; };
  }, [activeSessionRunId, client, sessionsEnabled]);
  const hasActiveRun = runs.some((item) => ["queued", "planning", "running"].includes(item.status));
  useEffect(() => {
    if (!hasActiveRun) return;
    const timer = window.setInterval(() => { void refresh(); }, 500);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, refresh]);
  useEffect(() => {
    if (providers.length === 0 && typeof (client as Partial<WeatherFlowClient>).modelProviders === "function") {
      void client.modelProviders().then((items) => setProviders(items));
    }
  }, [client, providers.length]);
  const submitChat = async (event: FormEvent) => {
    event.preventDefault();
    const intent = chatInput.trim();
    if (!intent || !selectedWorkspaceId || sending) return;
    setSending(true); setOperation(null);
    try {
      let targetSession = activeSession;
      if (sessionsEnabled && !targetSession) {
        const created = await client.createSession(selectedWorkspaceId);
        targetSession = created;
        setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
        setSelectedSessionId(created.id);
      }
      const contextRunId = sessionsEnabled ? targetSession?.latest_run_id ?? null : run?.id;
      const accepted = await client.createRun(intent, crypto.randomUUID(), selectedWorkspaceId, contextRunId, sessionsEnabled ? targetSession?.id : undefined, toolMode);
      selectedRunIdRef.current = accepted.id;
      setSelectedRunId(accepted.id);
      setRuns((current) => [accepted, ...current.filter((item) => item.id !== accepted.id)]);
      if (targetSession) {
        const session = targetSession;
        const title = session.title === "新对话" ? conversationTitle(intent) : session.title;
        let persistedSession: Session | null = null;
        if (session.title === "新对话") {
          try {
            persistedSession = await client.updateSession(session.id, selectedWorkspaceId, { title });
          } catch {
            setOperation("消息已发送，但会话标题暂未保存。");
          }
        }
        setSessions((current) => current.map((item) => item.id === session.id
          ? { ...item, ...persistedSession, latest_run_id: accepted.id, title, updated_at: accepted.updated_at }
          : item));
      }
      setChatInput("");
      try {
        await refresh(accepted.id);
      } catch {
        setOperation("消息已发送，但对话状态暂未刷新。任务会继续运行，请稍后再查看。");
      }
    } catch {
      setOperation("消息未发送；输入内容已保留，请重试。");
    } finally { setSending(false); }
  };
  const selectRun = (runId: string) => {
    const selected = runs.find((item) => item.id === runId);
    const owner = selected?.session_id ? sessions.find((item) => item.id === selected.session_id) : undefined;
    if (owner) setSelectedSessionId(owner.id);
    selectedRunIdRef.current = runId;
    setSelectedRunId(runId);
    void refresh(runId);
  };
  const selectSession = (session: Session) => {
    setSelectedSessionId(session.id);
    selectedRunIdRef.current = session.latest_run_id;
    setSelectedRunId(session.latest_run_id);
  };
  const createConversation = async () => {
    if (!selectedWorkspaceId || !sessionsEnabled) return;
    const created = await client.createSession(selectedWorkspaceId);
    setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    setSelectedSessionId(created.id);
    selectedRunIdRef.current = null; setSelectedRunId(null); setTimeline([]); setArtifacts([]); setUsage(null);
  };
  const updateConversation = async (sessionId: string, update: { title?: string; pinned?: boolean }) => {
    if (!selectedWorkspaceId) return;
    const updated = await client.updateSession(sessionId, selectedWorkspaceId, update);
    setSessions((current) => current.map((item) => item.id === sessionId ? updated : item));
  };
  const deleteConversation = async (session: Session) => {
    if (!selectedWorkspaceId) return;
    await client.deleteSession(session.id, selectedWorkspaceId);
    const remaining = sessions.filter((item) => item.id !== session.id).sort(compareSessions);
    setSessions(remaining);
    setRuns((current) => current.filter((item) => item.session_id !== session.id && item.id !== session.latest_run_id));
    if (selectedSessionId === session.id) {
      const next = remaining[0] ?? null;
      setSelectedSessionId(next?.id ?? null);
      selectedRunIdRef.current = next?.latest_run_id ?? null;
      setSelectedRunId(next?.latest_run_id ?? null);
      setTimeline([]);
      setArtifacts([]);
    }
    setOperation(`已永久删除对话“${session.title}”及其任务记录。`);
  };
  const decide = async (approval: Approval, decision: "approve" | "deny") => {
    await client.decide(approval.id, decision, approval.version, selectedWorkspaceId ?? snapshot?.workspace.id); await refresh();
  };
  const chooseWorkspace = async () => {
    const path = await nativeWindows.chooseWorkspaceDirectory();
    if (!path || !onAuthorizeWorkspace) return;
    const workspace = await onAuthorizeWorkspace(path);
    setOperation(`已授权项目 ${workspace.name}：${workspace.action_roots[0]}`);
  };
  const downloadArtifact = async (artifact: Artifact) => {
    const blob = await client.artifactContent(artifact.id); const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.name; anchor.click(); URL.revokeObjectURL(url);
  };

  return (
    <main className="cockpit-shell">
      <aside className="app-sidebar">
        <div className="brand"><Waves size={25} /><div><strong>WeatherFlow</strong><small>个人智能体</small></div></div>
        <nav aria-label="主导航">
          <NavButton active={view === "chat"} icon={<ChatCircleDots />} label="对话" onClick={() => setView("chat")} />
          <NavButton active={view === "runs"} icon={<ListChecks />} label="任务" badge={pending.length || undefined} onClick={() => setView("runs")} />
          <NavButton active={view === "watch"} icon={<Eye />} label="Watch" onClick={() => setView("watch")} />
          <span className="nav-group-label">工具</span>
          <NavButton active={view === "automations"} icon={<ClockCounterClockwise />} label="自动化" onClick={() => setView("automations")} />
          <NavButton active={view === "skills"} icon={<Brain />} label="Skills" onClick={() => setView("skills")} />
          <NavButton active={view === "mcp"} icon={<Pulse />} label="MCP Server" onClick={() => setView("mcp")} />
          <NavButton active={view === "models"} icon={<Robot />} label="LLM 模型" onClick={() => setView("models")} />
          <NavButton active={view === "oauth"} icon={<PlugsConnected />} label="OAuth" onClick={() => setView("oauth")} />
          <NavButton active={view === "settings"} icon={<GearSix />} label="设置" onClick={() => setView("settings")} />
        </nav>
        <div className="sidebar-project">
          <select aria-label="当前项目" value={selectedWorkspaceId ?? ""} onChange={(event) => onSelectWorkspace?.(event.target.value)}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select>
          <button aria-label="添加项目" title="添加项目" onClick={() => void chooseWorkspace()}><FolderOpen /><span>添加项目</span></button>
        </div>
        <div className={`local-status ${offline ? "offline" : ""}`}><i />{offline ? "内核离线" : "本机运行 · 数据私有"}</div>
      </aside>

      <section className="app-workspace">
        {view === "chat" && <ChatView client={client} providers={providers} workspaceId={selectedWorkspaceId} sessions={sessions} sessionsEnabled={sessionsEnabled} activeSession={activeSession} runs={runs} run={run} pending={pending} artifacts={artifacts} chatInput={chatInput} sending={sending} toolMode={toolMode} workspaceReady={Boolean(selectedWorkspaceId)} snapshot={snapshot} system={system} onInput={setChatInput} onToolMode={setToolMode} onSubmit={submitChat} onSelectRun={selectRun} onSelectSession={selectSession} onCreateSession={createConversation} onUpdateSession={updateConversation} onDeleteSession={deleteConversation} onDecide={decide} onDownload={downloadArtifact} onModelChanged={refresh} onOpenSettings={() => setView("models")} />}
        {view === "runs" && <RunsView runs={runs} run={run} usage={usage} timeline={timeline} artifacts={artifacts} pending={pending} onSelect={selectRun} onDecide={decide} onDownload={downloadArtifact} />}
        {view === "watch" && <WatchView client={client} workspaceId={selectedWorkspaceId} />}
        {view === "automations" && <AutomationView client={client} workspaceId={selectedWorkspaceId} onOperation={setOperation} />}
        {view === "skills" && <SkillsView client={client} workspace={selectedWorkspace} onOperation={setOperation} />}
        {view === "mcp" && <MCPServersView client={client} workspaceId={selectedWorkspaceId} onOperation={setOperation} />}
        {view === "models" && <SettingsView section="models" client={client} system={system} providers={providers} workspaceId={selectedWorkspaceId} offline={offline} snapshot={snapshot} resetPreview={resetPreview} onResetPreview={setResetPreview} onOperation={setOperation} onModelChanged={refresh} />}
        {view === "oauth" && <ConnectionsView client={client} workspaceId={selectedWorkspaceId} onOperation={setOperation} />}
        {view === "settings" && <SettingsView section="system" client={client} system={system} providers={providers} workspaceId={selectedWorkspaceId} offline={offline} snapshot={snapshot} resetPreview={resetPreview} onResetPreview={setResetPreview} onOperation={setOperation} onModelChanged={refresh} />}
        {operation && <div className="operation-toast" role="status">{operation}</div>}
      </section>
    </main>
  );
}

function NavButton({ active, icon, label, badge, onClick }: { active: boolean; icon: React.ReactElement; label: string; badge?: number; onClick: () => void }) {
  return <button className={active ? "active" : ""} aria-label={label} onClick={onClick}>{icon}<span>{label}</span>{badge && <b>{badge}</b>}</button>;
}

function ChatView({ client, providers, workspaceId, sessions, sessionsEnabled, activeSession, runs, run, pending, artifacts, chatInput, sending, toolMode, workspaceReady, snapshot, system, onInput, onToolMode, onSubmit, onSelectRun, onSelectSession, onCreateSession, onUpdateSession, onDeleteSession, onDecide, onDownload, onModelChanged, onOpenSettings }: { client: WeatherFlowClient; providers: ModelProviderPreset[]; workspaceId?: string | null; sessions: Session[]; sessionsEnabled: boolean; activeSession: Session | null; runs: Run[]; run: Run | null; pending: Approval[]; artifacts: Artifact[]; chatInput: string; sending: boolean; toolMode: ToolMode; workspaceReady: boolean; snapshot: DesktopSnapshot | null; system: SystemStatus | null; onInput: (value: string) => void; onToolMode: (value: ToolMode) => void; onSubmit: (event: FormEvent) => void; onSelectRun: (id: string) => void; onSelectSession: (session: Session) => void; onCreateSession: () => Promise<void>; onUpdateSession: (sessionId: string, update: { title?: string; pinned?: boolean }) => Promise<void>; onDeleteSession: (session: Session) => Promise<void>; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void; onModelChanged: () => Promise<void>; onOpenSettings: () => void }) {
  const scene = snapshot?.rhythm.weather.scene ?? "mixed";
  const composing = useRef(false);
  const displayedRuns = sessionsEnabled
    ? activeSession
      ? runs
        .filter((item) => item.session_id === activeSession.id || (!item.session_id && item.id === activeSession.latest_run_id))
        .sort((left, right) => Date.parse(left.updated_at) - Date.parse(right.updated_at))
      : []
    : [...runs].reverse();
  const chatReady = workspaceReady;
  return <div className={`chat-layout ${sessionsEnabled ? "has-session-rail" : ""}`}>
    {sessionsEnabled && <ConversationRail sessions={sessions} activeSessionId={activeSession?.id ?? null} workspaceReady={workspaceReady} onSelect={onSelectSession} onCreate={onCreateSession} onUpdate={onUpdateSession} onDelete={onDeleteSession} />}
    <section className="conversation-pane">
      <header className="workspace-header conversation-header">
        <div><span>对话</span><h1>今天想一起推进什么？</h1></div>
        <div className="conversation-signals">
          <div className="signal-chip weather" aria-label="人的状态天气" data-scene={scene}><CloudSun /><span><small>你的天气</small>{weatherText[scene]}</span></div>
          <div className="signal-chip task" aria-label="智能体任务状态"><span className={`run-dot ${run?.status ?? "idle"}`} /><span><small>当前任务</small>{run ? runStatusText[run.status] : "空闲"}</span></div>
        </div>
        {sessionsEnabled && <button className="mobile-new-session" type="button" aria-label="移动端新对话" disabled={!workspaceReady} onClick={() => void onCreateSession()}><Plus /><span>新对话</span></button>}
      </header>
      <div className="conversation-scroll">
        {displayedRuns.length === 0 && <div className="chat-empty"><h2>说出你真正想完成的事</h2><p>WeatherFlow 会结合你的状态调整协作方式，在后台保存任务进度，只在需要决定时打断你。</p><div className="empty-promises"><span><ShieldCheck /> 关键操作先批准</span><span><CheckCircle /> 任务进度可恢复</span></div></div>}
        {displayedRuns.map((item) => <article className={`conversation-turn ${item.id === run?.id ? "selected" : ""}`} key={item.id}>
          <div className="conversation-select" role="button" tabIndex={0} aria-label={`查看任务：${item.user_intent}`} onClick={() => { const selection = window.getSelection(); if (selection && !selection.isCollapsed) return; onSelectRun(item.id); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelectRun(item.id); } }}>
            <span className="message-label">你</span><div className="user-message">{item.user_intent}</div>
            <div className="assistant-message"><span className="message-label">WeatherFlow</span><p>{runMessage(item)}</p><small><span className={`run-dot ${item.status}`} />{runStatusText[item.status]} · {formatRelativeTime(item.updated_at)}</small></div>
          </div>
        </article>)}
      </div>
      <div className="composer-shell">
        <form className="chat-composer" onSubmit={(event) => { if (composing.current) { event.preventDefault(); return; } onSubmit(event); }}><textarea aria-label="对话输入" rows={1} value={chatInput} onChange={(event) => onInput(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229 && !composing.current) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={!workspaceReady ? "先在左下角选择或添加项目" : "给 WeatherFlow 发消息…"} /><button className="send-button" aria-label="发送" disabled={sending || !chatReady || !chatInput.trim()}><PaperPlaneRight weight="fill" /></button></form>
        <footer className="composer-meta">{workspaceReady ? <div className="composer-controls"><button className="attachment-button" type="button"><Paperclip /><span>添加附件</span></button><ModelSwitcher client={client} providers={providers} workspaceId={workspaceId} system={system} disabled={sending} onChanged={onModelChanged} onOpenSettings={onOpenSettings} /><ToolModeToggle value={toolMode} disabled={sending} onChange={onToolMode} /></div> : <span>先选择或添加一个项目，才能开始任务</span>}<span>Enter 发送 · Shift + Enter 换行</span></footer>
      </div>
    </section>
    <aside className="chat-context"><div className="context-heading"><ListDashes /><span>当前上下文</span></div><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside>
  </div>;
}

function ToolModeToggle({ value, disabled, onChange }: { value: ToolMode; disabled: boolean; onChange: (value: ToolMode) => void }) {
  return <div className="tool-mode-toggle" role="group" aria-label="工具模式">
    <button type="button" aria-pressed={value === "ask"} disabled={disabled} onClick={() => onChange("ask")} title="只向智能体提供读取工具">Ask</button>
    <button type="button" aria-pressed={value === "bypass"} disabled={disabled} onClick={() => onChange("bypass")} title="提供全部已审查工具；写入和破坏性操作仍需批准">Bypass</button>
  </div>;
}

function ConversationRail({ sessions, activeSessionId, workspaceReady, onSelect, onCreate, onUpdate, onDelete }: { sessions: Session[]; activeSessionId: string | null; workspaceReady: boolean; onSelect: (session: Session) => void; onCreate: () => Promise<void>; onUpdate: (sessionId: string, update: { title?: string; pinned?: boolean }) => Promise<void>; onDelete: (session: Session) => Promise<void> }) {
  const [query, setQuery] = useState("");
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLElement>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("zh-CN");
    return [...sessions].sort(compareSessions).filter((session) => !needle || session.title.toLocaleLowerCase("zh-CN").includes(needle));
  }, [query, sessions]);
  const pinned = filtered.filter((session) => session.pinned);
  const recent = filtered.filter((session) => !session.pinned);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setMenuSessionId(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const rename = async (session: Session) => {
    const title = draftTitle.trim();
    if (!title) return;
    setBusy(true);
    try { await onUpdate(session.id, { title }); setRenamingId(null); setMenuSessionId(null); }
    finally { setBusy(false); }
  };
  const togglePin = async (session: Session) => {
    setBusy(true);
    try { await onUpdate(session.id, { pinned: !session.pinned }); setMenuSessionId(null); }
    finally { setBusy(false); }
  };
  const permanentlyDelete = async (session: Session) => {
    setBusy(true);
    try {
      await onDelete(session);
      setDeleteSessionId(null);
      setMenuSessionId(null);
    } finally { setBusy(false); }
  };
  const group = (label: string, items: Session[]) => items.length > 0 && <section className="session-group" aria-label={label}>
    <h2>{label}</h2>
    {items.map((session) => <div className={`session-row ${session.id === activeSessionId ? "selected" : ""}`} key={session.id}>
      {renamingId === session.id
        ? <input autoFocus aria-label="重命名会话" value={draftTitle} disabled={busy} onChange={(event) => setDraftTitle(event.target.value)} onBlur={() => { if (!busy) void rename(session); }} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void rename(session); } if (event.key === "Escape") setRenamingId(null); }} />
        : <button type="button" className="session-open" aria-label={`打开会话：${session.title}`} aria-current={session.id === activeSessionId ? "true" : undefined} onClick={() => onSelect(session)}>{session.pinned && <PushPin weight="fill" />}<span>{session.title}</span></button>}
      <button type="button" className="session-more" aria-label={`会话选项：${session.title}`} aria-haspopup="menu" aria-expanded={menuSessionId === session.id} onClick={() => setMenuSessionId((current) => current === session.id ? null : session.id)}><DotsThree weight="bold" /></button>
      {menuSessionId === session.id && <div className="session-menu" role="menu">
        {deleteSessionId === session.id ? <div className="session-delete-confirm" role="alert">
          <p>这个对话及其任务记录会从本机永久删除。</p>
          <div><button type="button" onClick={() => setDeleteSessionId(null)}>取消</button><button type="button" className="danger" aria-label={`永久删除${session.title}`} disabled={busy} onClick={() => void permanentlyDelete(session)}>{busy ? "删除中…" : "永久删除"}</button></div>
        </div> : <>
          <button type="button" role="menuitem" onClick={() => { setDraftTitle(session.title); setRenamingId(session.id); setMenuSessionId(null); }}><PencilSimple />重命名</button>
          <button type="button" role="menuitem" onClick={() => void togglePin(session)} disabled={busy}><PushPin />{session.pinned ? "取消置顶" : "置顶"}</button>
          <button type="button" role="menuitem" className="danger" onClick={() => setDeleteSessionId(session.id)} disabled={busy}><Trash />删除对话</button>
        </>}
      </div>}
    </div>)}
  </section>;

  return <aside className="conversation-rail" aria-label="对话列表" ref={root}>
    <label className="session-search"><MagnifyingGlass /><input type="search" aria-label="搜索对话" placeholder="搜索对话" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    <button type="button" className="new-session" disabled={!workspaceReady || busy} onClick={() => void onCreate()}><Plus />新对话</button>
    <div className="session-list">{group("已置顶", pinned)}{group("最近", recent)}{filtered.length === 0 && <p className="session-empty">{query ? "没有匹配的对话" : "还没有对话"}</p>}</div>
  </aside>;
}

function ModelSwitcher({ client, providers, workspaceId, system, disabled, onChanged, onOpenSettings }: { client: WeatherFlowClient; providers: ModelProviderPreset[]; workspaceId?: string | null; system: SystemStatus | null; disabled: boolean; onChanged: () => Promise<void>; onOpenSettings: () => void }) {
  const [open, setOpen] = useState(false);
  const [credentialStatus, setCredentialStatus] = useState<Record<string, boolean>>({});
  const [selectedProvider, setSelectedProvider] = useState(system?.model?.provider ?? "minimax");
  const [catalogs, setCatalogs] = useState<Record<string, ProviderModel[]>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const activePreset = providers.find((item) => item.provider === system?.model?.provider);
  const activeLabel = activePreset?.label ?? system?.model?.provider ?? "模型";
  const configuredProviders = providers.filter((provider) => (
    credentialStatus[provider.provider]
    || (system?.model?.provider === provider.provider && Boolean(system.model.credential_available))
  ));
  const selectedPreset = providers.find((provider) => provider.provider === selectedProvider);
  const models = catalogs[selectedProvider] ?? (selectedPreset ? presetModelOptions(selectedPreset) : []);

  useEffect(() => {
    if (system?.model?.provider) setSelectedProvider(system.model.provider);
  }, [system?.model?.provider]);

  useEffect(() => {
    if (!open) return;
    let current = true;
    void Promise.all(providers.map(async (provider) => {
      try {
        const status = await nativeCredentials.status(provider.provider as CredentialProvider);
        return [provider.provider, status.key_present] as const;
      } catch {
        return [provider.provider, false] as const;
      }
    })).then((entries) => { if (current) setCredentialStatus(Object.fromEntries(entries)); });
    const closeOnOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", closeOnOutside);
    return () => { current = false; window.removeEventListener("pointerdown", closeOnOutside); };
  }, [open, providers]);

  const loadModels = useCallback(async (provider: ModelProviderPreset) => {
    if (catalogs[provider.provider]) return;
    setCatalogs((current) => ({ ...current, [provider.provider]: presetModelOptions(provider) }));
    if (typeof (client as Partial<WeatherFlowClient>).providerModels !== "function") return;
    try {
      const catalog = await client.providerModels(provider.provider);
      setCatalogs((current) => ({ ...current, [provider.provider]: catalog.models }));
    } catch {
      setError("暂时无法刷新这个密钥可用的模型，先显示官方推荐目录。");
    }
  }, [catalogs, client]);

  useEffect(() => {
    if (open && selectedPreset && configuredProviders.some((item) => item.provider === selectedPreset.provider)) {
      void loadModels(selectedPreset);
    }
  }, [configuredProviders, loadModels, open, selectedPreset]);

  const switchModel = async (provider: ModelProviderPreset, model: string) => {
    if (!workspaceId || busy) return;
    setBusy(true); setError(null);
    try {
      await client.configureModel({
        provider: provider.provider,
        model,
        base_url: provider.base_url,
        ...(provider.provider === "minimax" ? { billing_origin: system?.model?.billing_origin ?? null } : {}),
      }, workspaceId);
      await onChanged();
      setOpen(false);
    } catch {
      setError("模型切换失败，请检查该提供商的额度和网络连接。");
    } finally { setBusy(false); }
  };

  const label = system?.model?.configured && system.model.model
    ? `当前模型：${activeLabel} · ${system.model.model}`
    : "当前模型：尚未配置";
  return <div className="model-switcher" ref={root}>
    <button type="button" className="model-switcher-trigger" aria-label={label} aria-expanded={open} disabled={disabled} onClick={() => setOpen((value) => !value)}><Robot /><span>{system?.model?.configured && system.model.model ? `${activeLabel} · ${system.model.model}` : "模型尚未配置"}</span><CaretDown /></button>
    {open && <div className="model-switcher-popover" role="dialog" aria-label="切换语言模型">
      <div className="model-switcher-heading"><strong>为下一条消息选择模型</strong><small>完全由你选择，不做智能路由</small></div>
      {configuredProviders.length === 0 ? <div className="model-switcher-empty"><p>还没有已配置的模型提供商。</p><button type="button" onClick={() => { setOpen(false); onOpenSettings(); }}>前往模型设置</button></div> : <>
        <div className="model-switcher-providers">{configuredProviders.map((provider) => <button type="button" aria-label={`选择 ${provider.label}`} className={selectedProvider === provider.provider ? "selected" : ""} key={provider.provider} onClick={() => { setSelectedProvider(provider.provider); setError(null); void loadModels(provider); }}>{provider.label}</button>)}</div>
        <div className="model-switcher-models">{models.map((model) => {
          const active = system?.model?.provider === selectedProvider && system.model.model === model.id;
          return <button type="button" aria-label={`使用 ${model.id}`} className={`${active ? "active" : ""} ${!model.selectable ? "incompatible" : ""}`} key={model.id} disabled={busy || active || !model.selectable} title={model.note ?? undefined} onClick={() => selectedPreset && void switchModel(selectedPreset, model.id)}><span>{model.id}{model.note && <small>{model.note}</small>}</span>{active && <Check />}</button>;
        })}</div>
      </>}
      {error && <p className="model-switcher-error" role="alert">{error}</p>}
    </div>}
  </div>;
}

function ContextContent({ pending, artifacts, onDecide, onDownload }: { pending: Approval[]; artifacts: Artifact[]; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <><section><h3>待批准</h3>{pending.length === 0 ? <p>没有需要处理的操作。</p> : pending.map((approval) => <article className="approval-card" key={approval.id}><strong>{approval.tool_id}</strong><pre>{JSON.stringify(approval.preview, null, 2)}</pre><div><button onClick={() => void onDecide(approval, "deny")}>拒绝</button><button className="primary" onClick={() => void onDecide(approval, "approve")}>批准</button></div></article>)}</section><section><h3>产出文件</h3>{artifacts.length === 0 ? <p>暂无文件。</p> : artifacts.map((artifact) => <button className="artifact-link" key={artifact.id} onClick={() => void onDownload(artifact)}>{artifact.name}<small>{artifact.size_bytes} 字节</small></button>)}</section></>;
}

function RunsView({ runs, run, usage, timeline, artifacts, pending, onSelect, onDecide, onDownload }: { runs: Run[]; run: Run | null; usage: RunUsage | null; timeline: LedgerEvent[]; artifacts: Artifact[]; pending: Approval[]; onSelect: (id: string) => void; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <div className="page-view"><header className="page-header"><span>任务</span><h1>执行、批准与产出</h1><p>这里只展示 Agent 的任务状态；人的状态理解与任务成败保持分离。</p></header><div className="runs-layout"><nav className="run-list" aria-label="任务列表">{runs.length === 0 ? <div className="run-list-empty">暂无任务</div> : runs.map((item) => <button className={item.id === run?.id ? "selected" : ""} key={item.id} onClick={() => onSelect(item.id)} aria-pressed={item.id === run?.id} aria-label={`${item.user_intent}，${runStatusText[item.status]}`}><span>{item.user_intent}</span><small><i className={`run-dot ${item.status}`} />{runStatusText[item.status]} · {formatRelativeTime(item.updated_at)}</small></button>)}</nav><section className="run-detail">{run ? <><div className="run-detail-heading"><span className={`status-pill ${run.status}`}>{runStatusText[run.status]}</span><time>{formatRelativeTime(run.updated_at)}</time></div><h2>{run.user_intent}</h2><div className="run-result"><span>当前结果</span><p>{runMessage(run)}</p></div><RunUsagePanel usage={usage} /><div className="section-heading"><h3>执行记录</h3><small>{timeline.length} 个事件</small></div>{timeline.length ? <ol className="timeline">{timeline.slice(-12).reverse().map((event) => <li key={event.id}><i /><div><strong>{formatEventType(event.type)}</strong><time>{new Date(event.recorded_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div></li>)}</ol> : <div className="detail-empty">等待第一条执行记录</div>}</> : <div className="detail-empty centered">选择一个任务查看完整执行记录</div>}</section><aside className="run-context"><div className="context-heading"><Wrench /><span>任务上下文</span></div><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside></div></div>;
}

function RunUsagePanel({ usage }: { usage: RunUsage | null }) {
  if (!usage) return <section className="run-usage" aria-label="Run 用量与预算"><div className="section-heading"><h3>用量与预算</h3></div><p>用量数据暂不可用。</p></section>;
  const model = usage.provider && usage.model ? `${usage.provider} · ${usage.model}` : "模型路由未绑定";
  const cost = usage.cost_status === "known" && usage.cost_amount !== null && usage.currency
    ? `${usage.currency === "USD" ? "$" : "CNY "}${usage.cost_amount.toFixed(6)}`
    : "成本未知";
  const pricing = usage.pricing_catalog_version ?? "无可靠定价目录";
  const failure = usage.cost_failure_reason === "cost_unknown"
    ? "成本未知，有限预算已按安全策略终止。"
    : usage.cost_failure_reason === "cost_budget_exhausted"
      ? "成本预算已耗尽，Run 已按安全策略终止。"
      : null;
  return <section className="run-usage" aria-label="Run 用量与预算">
    <div className="section-heading"><h3>用量与预算</h3><small>{usage.schema_version}</small></div>
    <dl>
      <div><dt>模型</dt><dd>{model}</dd></div>
      <div><dt>Token</dt><dd>输入 {usage.input_tokens.toLocaleString("zh-CN")} · 缓存命中 {usage.cache_read_input_tokens === null ? "未知" : usage.cache_read_input_tokens.toLocaleString("zh-CN")} · 输出 {usage.output_tokens.toLocaleString("zh-CN")} · 总计 {usage.total_tokens.toLocaleString("zh-CN")}</dd></div>
      <div><dt>成本</dt><dd className={usage.cost_status === "unknown" ? "unknown" : ""}>{cost}</dd></div>
      <div><dt>口径</dt><dd>{usage.cost_scope} · {usage.billing_origin ?? "计费来源未确认"}</dd></div>
      <div><dt>定价</dt><dd>{pricing}</dd></div>
      <div><dt>预算</dt><dd>{formatCostBudget(usage)}</dd></div>
      <div><dt>进度</dt><dd>{usage.step_count} 步 · 已运行 {formatDuration(usage.elapsed_seconds)} · 超时上限 {formatDuration(usage.timeout_seconds)}</dd></div>
    </dl>
    {failure && <p className="run-usage-failure" role="alert">{failure}</p>}
  </section>;
}

function formatCostBudget(usage: RunUsage): string {
  if (usage.cost_budget_status === "unlimited") return "未设置成本上限";
  if (usage.cost_budget_status === "pending_usage") return `上限 $${(usage.max_cost_usd ?? 0).toFixed(6)} · 等待首次模型用量`;
  if (usage.cost_budget_status === "unknown_cost") return `上限 $${(usage.max_cost_usd ?? 0).toFixed(6)} · 成本未知，无法计算占用`;
  const percent = usage.cost_budget_usage_percent === null ? "占用比例不可计算" : `已用 ${usage.cost_budget_usage_percent.toFixed(1)}%`;
  return `上限 $${(usage.max_cost_usd ?? 0).toFixed(6)} · ${percent}`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`;
  if (seconds < 3_600) return `${(seconds / 60).toFixed(1)} 分钟`;
  return `${(seconds / 3_600).toFixed(1)} 小时`;
}

function formatRelativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "时间未知";
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return new Date(timestamp).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function runMessage(run: Run): string {
  if (run.result_summary) return run.result_summary;
  if (
    run.status === "failed"
    && ["KeyringError", "CredentialUnavailableError", "MiniMaxAuthenticationError"].includes(run.error_class ?? "")
  ) {
    return "无法读取模型密钥，请到“LLM 模型”重新粘贴 API Key。";
  }
  return `任务${runStatusText[run.status]}`;
}

function formatEventType(type: string) {
  const labels: Record<string, string> = {
    "run.created": "任务已创建", "run.status_changed": "任务状态已更新",
    "run.result_committed": "结果已保存", "runtime.turn_recorded": "模型回合已保存",
    "capability.snapshot_frozen": "能力快照已冻结", "run.rhythm_policy_bound": "状态策略已绑定",
    "provider.degraded": "模型提供商已降级", "rhythm.snapshot_derived": "状态天气已更新",
    "rhythm.signal.task_behavior": "任务行为信号已记录",
  };
  return labels[type] ?? type.replaceAll(".", " · ");
}

const connectorPresentation: Record<ConnectorKind, { note: string; icon: React.ReactElement }> = {
  github: { note: "仓库、Issue 与 Pull Request", icon: <SiGithub className="connector-brand-icon" /> },
  gmail: { note: "邮件、会话与草稿", icon: <SiGmail className="connector-brand-icon" /> },
  google_calendar: { note: "日程、空闲时间与会议", icon: <SiGooglecalendar className="connector-brand-icon" /> },
  slack: { note: "频道、消息与团队协作", icon: <SlackLogo className="connector-brand-icon" weight="fill" /> },
  notion: { note: "页面、数据库与知识库", icon: <SiNotion className="connector-brand-icon" /> },
  google_drive: { note: "云端文件与共享空间", icon: <SiGoogledrive className="connector-brand-icon" /> },
  google_sheets: { note: "表格、工作表与数据", icon: <SiGooglesheets className="connector-brand-icon" /> },
  outlook: { note: "Microsoft 邮件与日历", icon: <MicrosoftOutlookLogo className="connector-brand-icon" weight="fill" /> },
  one_drive: { note: "Microsoft 云端文件", icon: <Cloud className="connector-brand-icon" weight="fill" /> },
  microsoft_teams: { note: "团队频道、会议与聊天", icon: <MicrosoftTeamsLogo className="connector-brand-icon" weight="fill" /> },
  linear: { note: "产品问题与项目进度", icon: <SiLinear className="connector-brand-icon" /> },
  jira: { note: "问题、看板与发布计划", icon: <SiJira className="connector-brand-icon" /> },
  confluence: { note: "团队知识库与页面", icon: <SiConfluence className="connector-brand-icon" /> },
  dropbox: { note: "文件、目录与共享链接", icon: <SiDropbox className="connector-brand-icon" /> },
  gitlab: { note: "代码、Issue 与合并请求", icon: <SiGitlab className="connector-brand-icon" /> },
  discord: { note: "服务器、频道与社区", icon: <SiDiscord className="connector-brand-icon" /> },
  trello: { note: "看板、列表与卡片", icon: <SiTrello className="connector-brand-icon" /> },
  asana: { note: "任务、项目与团队计划", icon: <SiAsana className="connector-brand-icon" /> },
  airtable: { note: "数据库、表格与记录", icon: <SiAirtable className="connector-brand-icon" /> },
  clickup: { note: "任务、文档与工作流", icon: <SiClickup className="connector-brand-icon" /> },
};

type OAuthCategory = "all" | "communication" | "productivity" | "development" | "platform";
const oauthCategories: { id: OAuthCategory; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "communication", label: "沟通" },
  { id: "productivity", label: "生产力" },
  { id: "development", label: "开发与自动化" },
  { id: "platform", label: "平台" },
];

const composioMinimumPermissions = "最小权限：Auth configs 读写、Connected accounts 读写、Toolkits 读取、Tool execution 写入。";

function normalizeOAuthCategory(category: string): Exclude<OAuthCategory, "all"> {
  if (["chat", "communication", "social"].includes(category)) return "communication";
  if (["development", "tools", "tools_automation", "automation"].includes(category)) return "development";
  if (category === "platform") return "platform";
  return "productivity";
}

function effectiveOAuthSetup(status: ConnectorStatus) {
  return status.oauth_setup ?? (["github", "gmail", "google_calendar"].includes(status.connector) ? "managed" : "unknown");
}

function supportsAutoFetch(status: ConnectorStatus) {
  return status.auto_fetch_supported ?? ["github", "gmail", "google_calendar"].includes(status.connector);
}

function supportsConversationTools(status: ConnectorStatus) {
  return status.conversation_tools_supported ?? ["github", "gmail", "google_calendar"].includes(status.connector);
}

function oauthState(status: ConnectorStatus): { label: string; tone: string } {
  if (status.last_error_code === "broker_auth") return { label: "连接服务失效", tone: "error" };
  if (status.last_error_code === "broker_permission") return { label: "连接服务权限不足", tone: "error" };
  if (status.last_error_code === "project_changed") return { label: "项目已更换，需要重新授权", tone: "error" };
  if (status.connected) return { label: "已连接", tone: "connected" };
  if (status.phase === "waiting_user" || Boolean(status.attempt_id)) return { label: "等待授权", tone: "waiting" };
  if (!status.configured) return { label: "未配置", tone: "unconfigured" };
  if (effectiveOAuthSetup(status) === "managed") return { label: "可一键连接", tone: "ready" };
  if (effectiveOAuthSetup(status) === "bring_your_own") return { label: "需要 OAuth 应用", tone: "requires-app" };
  return { label: "未配置", tone: "unconfigured" };
}

function ConnectionsView({ client, workspaceId, onOperation }: { client: WeatherFlowClient; workspaceId?: string | null; onOperation: (value: string) => void }) {
  const [statuses, setStatuses] = useState<ConnectorStatus[]>([]);
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [apiKey, setApiKey] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<OAuthCategory>("all");
  const [selectedConnector, setSelectedConnector] = useState<ConnectorKind | null>(null);
  const [busy, setBusy] = useState<ConnectorKind | "configure" | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<ConnectorKind | null>(null);
  const [handoffs, setHandoffs] = useState<Partial<Record<ConnectorKind, string>>>({});
  const connecting = useRef(new Set<ConnectorKind>());
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    if (!workspaceId) {
      if (mounted.current) {
        setStatuses([]);
        setCatalogState("ready");
      }
      return;
    }
    setCatalogState("loading");
    try {
      const nextStatuses = await client.connectors(workspaceId);
      if (!mounted.current) return;
      setStatuses(nextStatuses);
      setCatalogState("ready");
    } catch {
      if (mounted.current) setCatalogState("error");
    }
  }, [client, workspaceId]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  const configured = statuses.some((status) => status.configured);
  const brokerCredentialInvalid = statuses.some((status) => status.last_error_code === "broker_auth");
  const brokerCredentialPermissionMissing = statuses.some((status) => status.last_error_code === "broker_permission");
  const brokerCredentialIssue = brokerCredentialInvalid || brokerCredentialPermissionMissing;
  const visibleStatuses = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    return statuses.filter((status) => {
      const matchesCategory = category === "all" || normalizeOAuthCategory(status.category ?? "productivity") === category;
      const presentation = connectorPresentation[status.connector];
      const matchesQuery = !query || `${status.label} ${status.toolkit ?? status.connector} ${presentation.note}`.toLocaleLowerCase("zh-CN").includes(query);
      return matchesCategory && matchesQuery;
    });
  }, [category, search, statuses]);
  const selectedStatus = statuses.find((status) => status.connector === selectedConnector) ?? null;
  const configure = async (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim() || busy) return;
    setBusy("configure");
    let storedNewCredential = false;
    try {
      const existing = await nativeCredentials.status("composio");
      if (existing.key_present) {
        await refresh();
        onOperation("Composio 密钥已经存在；如需更换，请先删除底层密钥。现有密钥未被改动。");
        return;
      }
      await nativeCredentials.set("composio", apiKey.trim());
      storedNewCredential = true;
      await client.configureConnectors();
      setApiKey("");
      await refresh();
      onOperation("Composio 项目密钥已验证并保存到本机钥匙串。");
    } catch (error) {
      const permissionFailure = error instanceof WeatherFlowBridgeError
        && error.code === "connector_broker_permission";
      if (storedNewCredential) {
        try {
          await nativeCredentials.delete("composio");
        } catch {
          onOperation(permissionFailure
            ? `Composio 密钥权限不足，且无法自动移除刚写入的密钥；请删除底层密钥后重试。${composioMinimumPermissions}`
            : "Composio 密钥验证失败，且无法自动移除刚写入的密钥；请删除底层密钥后重试。");
          return;
        }
        try { await refresh(); } catch { /* The unconfigured form remains locally retryable. */ }
        onOperation(permissionFailure
          ? `Composio 密钥权限不足；新密钥已删除。${composioMinimumPermissions}`
          : "Composio 密钥验证失败；密钥未保存，请检查项目密钥与网络连接后重试。");
      } else {
        onOperation("无法保存 Composio 密钥，请确认本机钥匙串可用后重试。");
      }
    } finally { setBusy(null); }
  };

  const removeCredential = async () => {
    if (busy) return;
    setBusy("configure");
    try {
      await nativeCredentials.delete("composio");
      await refresh();
      onOperation("Composio 项目密钥已从 WeatherFlow 删除。");
    } catch {
      onOperation("暂时无法删除 Composio 项目密钥，请稍后重试。");
    } finally { setBusy(null); }
  };

  const pollAttempt = useCallback((connector: ConnectorKind, label: string, attemptId: string, deadline: number): void => {
    window.setTimeout(async () => {
      if (!mounted.current || Date.now() >= deadline || typeof (client as Partial<WeatherFlowClient>).connectorAttempt !== "function") {
        connecting.current.delete(connector);
        if (mounted.current && Date.now() >= deadline) {
          await refresh();
          onOperation(`${label} 授权已超时，请重新连接。`);
        }
        return;
      }
      try {
        const attempt: ConnectionAttempt = await client.connectorAttempt(attemptId);
        if (attempt.phase === "active") {
          connecting.current.delete(connector);
          setHandoffs((current) => ({ ...current, [connector]: undefined }));
          await refresh();
          onOperation("连接成功；可在详情中分别开启自动抓取和对话权限。");
          return;
        }
        if (["expired", "error", "revoked"].includes(attempt.phase)) {
          connecting.current.delete(connector);
          await refresh();
          onOperation("连接没有完成，请重新尝试授权。");
          return;
        }
      } catch {
        // A transient bridge failure does not create another overlapping poll.
      }
      pollAttempt(connector, label, attemptId, deadline);
    }, 4000);
  }, [client, onOperation, refresh]);

  useEffect(() => {
    for (const status of statuses) {
      if (!status.attempt_id || !status.attempt_expires_at || connecting.current.has(status.connector)) continue;
      connecting.current.add(status.connector);
      const remoteExpiry = Date.parse(status.attempt_expires_at);
      pollAttempt(
        status.connector,
        status.label,
        status.attempt_id,
        Math.min(Date.now() + 300_000, Number.isNaN(remoteExpiry) ? Infinity : remoteExpiry),
      );
    }
  }, [pollAttempt, statuses]);

  const connect = async (connector: ConnectorKind, label: string) => {
    if (!workspaceId || connecting.current.has(connector)) return;
    connecting.current.add(connector);
    setBusy(connector);
    try {
      const handoff = await client.connectConnector(connector, workspaceId);
      setHandoffs((current) => ({ ...current, [connector]: handoff.connect_url }));
      await nativeWindows.openConnectorUrl(handoff.connect_url);
      const remoteExpiry = Date.parse(handoff.expires_at);
      pollAttempt(connector, label, handoff.attempt_id, Math.min(Date.now() + 300_000, Number.isNaN(remoteExpiry) ? Infinity : remoteExpiry));
      onOperation("已在系统浏览器打开授权页，WeatherFlow 正在等待授权结果。");
    } catch {
      connecting.current.delete(connector);
      const status = statuses.find((item) => item.connector === connector);
      onOperation(status && effectiveOAuthSetup(status) === "bring_your_own"
        ? `无法启动 ${label} 授权，请先在 Composio 项目中配置该服务的 OAuth 应用。`
        : "无法启动连接；如果授权页已生成，可点击“重新打开授权页”。");
    } finally { setBusy(null); }
  };

  const updateSettings = async (status: ConnectorStatus, autoFetchEnabled: boolean) => {
    if (!workspaceId) return;
    setBusy(status.connector);
    try {
      await client.updateConnectorSettings(status.connector, autoFetchEnabled, 1440, workspaceId);
      await refresh();
    } finally { setBusy(null); }
  };
  const sync = async (status: ConnectorStatus) => {
    if (!workspaceId) return;
    setBusy(status.connector);
    try {
      const snapshot = await client.syncConnector(status.connector, workspaceId);
      await refresh();
      onOperation(`${status.label} 已抓取 ${snapshot.items.length} 条只读信息。`);
    } catch { onOperation(`${status.label} 抓取失败；不会自动重试有副作用的操作。`); }
    finally { setBusy(null); }
  };
  const disconnect = async (status: ConnectorStatus) => {
    setBusy(status.connector);
    try {
      await client.disconnectConnector(status.connector, workspaceId);
      setConfirmDisconnect(null);
      await refresh();
      onOperation(`${status.label} 已断开，WeatherFlow 本地保存的该连接摘要也已删除。`);
    } finally { setBusy(null); }
  };

  return <div className="page-view connections-view">
    <header className="page-header"><span>OAuth</span><h1>连接你的常用服务</h1><p>使用你的账号授权 WeatherFlow 读取信息或准备操作。服务商令牌由连接代理托管；对话中的工具范围统一由输入框下方的 Ask / Bypass 模式决定。</p></header>
    <div className="oauth-catalog-toolbar">
      <label className="oauth-search"><MagnifyingGlass /><input type="search" aria-label="搜索 OAuth 服务" placeholder="搜索服务…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <div className="oauth-categories" aria-label="OAuth 服务分类">{oauthCategories.map((item) => <button type="button" className={category === item.id ? "active" : ""} aria-pressed={category === item.id} key={item.id} onClick={() => setCategory(item.id)}>{item.label}</button>)}</div>
    </div>
    <div className="oauth-catalog-grid">{visibleStatuses.map((status) => {
      const state = oauthState(status);
      const presentation = connectorPresentation[status.connector];
      return <button type="button" aria-label={`查看 ${status.label}`} aria-pressed={selectedStatus?.connector === status.connector} className={`oauth-service-card ${state.tone} ${selectedStatus?.connector === status.connector ? "selected" : ""}`} data-connector={status.connector} key={status.connector} onClick={() => setSelectedConnector(status.connector)}>
        <span className="oauth-service-mark">{presentation.icon}</span>
        <strong>{status.label}</strong>
        <small>{state.label}</small>
      </button>;
    })}</div>
    {catalogState === "loading" && statuses.length === 0 && <div className="oauth-empty" role="status"><MagnifyingGlass /><strong>正在加载 OAuth 服务</strong><span>正在读取本机连接状态与可用服务目录。</span></div>}
    {catalogState === "error" && <div className="oauth-empty" role="alert"><WarningCircle /><strong>OAuth 服务目录加载失败</strong><span>连接状态未被修改；请检查本机服务后重试。</span><button type="button" onClick={() => void refresh()}>重试加载 OAuth 服务</button></div>}
    {catalogState === "ready" && visibleStatuses.length === 0 && <div className="oauth-empty"><MagnifyingGlass /><strong>没有匹配的服务</strong><span>试试服务名称或切换分类。</span></div>}
    {selectedStatus && <ConnectorDetail status={selectedStatus} configured={configured} busy={busy} handoffUrl={handoffs[selectedStatus.connector]} confirmDisconnect={confirmDisconnect === selectedStatus.connector} onConnect={connect} onReopen={(url) => nativeWindows.openConnectorUrl(url)} onSettings={updateSettings} onSync={sync} onConfirmDisconnect={() => setConfirmDisconnect(selectedStatus.connector)} onDisconnect={disconnect} />}
    <details className={`oauth-broker-settings${brokerCredentialIssue ? " invalid" : ""}`} open={!configured || brokerCredentialIssue || undefined}>
      <summary><span>{brokerCredentialIssue ? <WarningCircle /> : <ShieldCheck />}OAuth 连接服务</span><small>{brokerCredentialInvalid ? "连接密钥失效" : brokerCredentialPermissionMissing ? "连接服务权限不足" : configured ? "已安全配置" : "需要配置"}</small></summary>
      {!configured ? <form className="connector-key-form" onSubmit={configure}><div><h2>高级配置 · Composio</h2><p>WeatherFlow 使用 scoped project API key 创建 OAuth Connect Link。密钥只保存在本机钥匙串，不进入对话或日志。</p></div><label>Composio Project API Key<input aria-label="Composio Project API Key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="cmp_…" /></label><button className="primary" disabled={!apiKey.trim() || busy === "configure"}>验证并保存连接密钥</button></form> : <div className={`credential-summary${brokerCredentialIssue ? " invalid" : ""}`}><div className="credential-summary-copy"><span>{brokerCredentialIssue ? <WarningCircle size={18} /> : <ShieldCheck size={18} />}<span>{brokerCredentialInvalid ? "Composio 连接密钥失效，请删除后重新配置。" : brokerCredentialPermissionMissing ? "Composio 密钥权限不足，请补齐连接服务所需权限。" : "OAuth 连接服务已由 WeatherFlow 安全配置"}</span></span>{brokerCredentialPermissionMissing && <small>{composioMinimumPermissions}</small>}</div><button type="button" onClick={() => void removeCredential()} disabled={Boolean(busy)}>{brokerCredentialInvalid ? "删除失效密钥并重新配置" : brokerCredentialPermissionMissing ? "删除密钥并重新配置权限" : "删除底层密钥"}</button></div>}
    </details>
  </div>;
}

function ConnectorDetail({ status, configured, busy, handoffUrl, confirmDisconnect, onConnect, onReopen, onSettings, onSync, onConfirmDisconnect, onDisconnect }: { status: ConnectorStatus; configured: boolean; busy: ConnectorKind | "configure" | null; handoffUrl?: string; confirmDisconnect: boolean; onConnect: (connector: ConnectorKind, label: string) => Promise<void>; onReopen: (url: string) => Promise<void>; onSettings: (status: ConnectorStatus, enabled: boolean) => Promise<void>; onSync: (status: ConnectorStatus) => Promise<void>; onConfirmDisconnect: () => void; onDisconnect: (status: ConnectorStatus) => Promise<void> }) {
  const presentation = connectorPresentation[status.connector];
  const state = oauthState(status);
  const isBusy = busy === status.connector;
  const isWaiting = state.tone === "waiting";
  const setup = effectiveOAuthSetup(status);
  const autoFetchSupported = supportsAutoFetch(status);
  const conversationToolsSupported = supportsConversationTools(status);
  const availableToolIds = status.available_tool_ids;
  const canStartOAuth = configured && setup !== "unknown";
  const projectChanged = status.last_error_code === "project_changed";
  const showConnected = status.connected && !projectChanged;
  return <section className="oauth-detail" data-connector={status.connector} aria-label={`${status.label} 连接详情`}>
    <header><span className="oauth-detail-mark">{presentation.icon}</span><div><small>{state.label}</small><h2>{status.label}</h2><p>{presentation.note}</p></div><span className={`oauth-detail-state ${state.tone}`}>{state.label}</span></header>
    {showConnected ? <div className="oauth-detail-body">
      <div className="oauth-account"><span>当前账号</span><strong>{status.display_name || "授权账号"}</strong></div>
      {conversationToolsSupported ? <div className="oauth-capability-notice available"><Wrench /><div><strong>已接入统一工具模式</strong><p>Ask 提供全部读取工具；Bypass 提供全部已审查工具。创建、修改和删除仍会在执行前逐次向你确认。</p><details className="connector-tool-disclosure"><summary>{`已审查 ${availableToolIds.length} 个固定工具`}</summary>{availableToolIds.length > 0 && <ul>{availableToolIds.map((toolId) => <li key={toolId}><code>{toolId}</code></li>)}</ul>}</details></div></div> : <div className="oauth-capability-notice"><Wrench /><div><strong>对话工具待审阅</strong><p>连接后暂不能在对话中使用，固定工具仍在审阅中。</p></div></div>}
      {autoFetchSupported ? <div className="oauth-fetch-settings"><label className="connector-toggle"><input type="checkbox" aria-label="自动抓取" checked={status.auto_fetch_enabled} onChange={(event) => void onSettings(status, event.target.checked)} disabled={isBusy} /><span>自动抓取</span></label><span className="connector-cadence">每天自动刷新</span><small>{status.last_sync_at ? `上次抓取 ${new Date(status.last_sync_at).toLocaleString("zh-CN")}` : "尚未完成首次抓取"}</small></div> : <p className="oauth-unavailable-note">该服务暂不支持后台自动抓取。</p>}
      <div className="connector-actions">{autoFetchSupported && <button onClick={() => void onSync(status)} disabled={isBusy}>立即抓取</button>}{confirmDisconnect ? <button className="danger" onClick={() => void onDisconnect(status)} disabled={isBusy}>确认断开并删除摘要</button> : <button onClick={onConfirmDisconnect}>断开连接</button>}</div>
    </div> : <div className="oauth-connect-panel">
      <div><strong>{projectChanged ? "Composio 项目已更换，需要重新连接" : setup === "bring_your_own" ? "需要先配置 OAuth 应用" : setup === "managed" ? "使用系统浏览器完成授权" : "授权方式尚未配置"}</strong><p>{projectChanged ? "原连接属于之前的 Composio 项目；请在当前项目中重新完成账号授权。" : !configured ? "请先在下方配置 OAuth 连接服务。" : setup === "bring_your_own" ? "这个服务需要在 Composio 项目中配置你自己的 OAuth Client；完成后再返回连接。" : setup === "managed" ? "WeatherFlow 只接收不透明的账号引用，不会接触服务商访问令牌。" : "该服务尚未确认可用的 OAuth 配置，因此保持关闭。"}</p>{!conversationToolsSupported && <p className="oauth-tool-warning">连接后暂不能在对话中使用，固定工具仍在审阅中。</p>}</div>
      {setup !== "unknown" && <button className="connect-button" onClick={() => void onConnect(status.connector, status.label)} disabled={!canStartOAuth || isBusy || isWaiting} aria-label={`${projectChanged ? "重新连接" : "连接"} ${status.label}`}>{isWaiting ? "等待浏览器授权…" : projectChanged ? `重新连接 ${status.label}` : setup === "bring_your_own" ? "已配置应用，开始连接" : `连接 ${status.label}`}</button>}
      {setup === "unknown" && <button className="connect-button" disabled>暂不可连接</button>}
      {handoffUrl && <button className="link-button" onClick={() => void onReopen(handoffUrl)}>重新打开授权页</button>}
    </div>}
  </section>;
}

function SettingsView({ section, client, system, providers, workspaceId, offline, snapshot, resetPreview, onResetPreview, onOperation, onModelChanged }: { section: "models" | "system"; client: WeatherFlowClient; system: SystemStatus | null; providers: ModelProviderPreset[]; workspaceId?: string | null; offline: boolean; snapshot: DesktopSnapshot | null; resetPreview: ResetPreview | null; onResetPreview: (value: ResetPreview | null) => void; onOperation: (value: string) => void; onModelChanged: () => Promise<void> }) {
  const [theme, setTheme] = useState<ThemePreference>(() => getThemePreference());
  const [selectedProvider, setSelectedProvider] = useState(system?.model?.provider ?? "minimax");
  const [credentialStatus, setCredentialStatus] = useState<Record<string, boolean>>({});
  const [catalogs, setCatalogs] = useState<Record<string, ProviderModel[]>>({});
  const [model, setModel] = useState(system?.model?.model ?? "MiniMax-M3");
  const [billingOrigin, setBillingOrigin] = useState<BillingOrigin | "">(system?.model?.billing_origin ?? "");
  const [modelSearch, setModelSearch] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [editingKey, setEditingKey] = useState(false);
  const [configureError, setConfigureError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState(false);
  const [summarySettings, setSummarySettings] = useState<ActivitySummarySettings | null>(null);
  const [summaryModel, setSummaryModel] = useState("");
  const [summaryModels, setSummaryModels] = useState<ProviderModel[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summarySaving, setSummarySaving] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const preset = providers.find((item) => item.provider === selectedProvider);
  const activeForProvider = system?.model?.provider === selectedProvider;
  const credentialPresent = credentialStatus[selectedProvider]
    ?? (activeForProvider && Boolean(system?.model?.credential_available));
  const availableModels = catalogs[selectedProvider] ?? (preset ? presetModelOptions(preset) : []);
  const visibleModels = availableModels.filter((item) => item.id.toLowerCase().includes(modelSearch.trim().toLowerCase())).slice(0, 120);

  useEffect(() => {
    if (system?.model?.configured && system.model.provider) {
      setSelectedProvider(system.model.provider);
      if (system.model.model) setModel(system.model.model);
      setBillingOrigin(system.model.billing_origin ?? "");
    }
  }, [system?.model?.billing_origin, system?.model?.configured, system?.model?.model, system?.model?.provider]);

  useEffect(() => {
    let current = true;
    void Promise.all(providers.map(async (provider) => {
      try {
        const status = await nativeCredentials.status(provider.provider as CredentialProvider);
        return [provider.provider, status.key_present] as const;
      } catch {
        return [provider.provider, false] as const;
      }
    })).then((entries) => { if (current) setCredentialStatus(Object.fromEntries(entries)); });
    return () => { current = false; };
  }, [providers]);

  const loadModels = useCallback(async (provider: ModelProviderPreset): Promise<ProviderModel[]> => {
    const fallback = presetModelOptions(provider);
    setCatalogs((current) => ({ ...current, [provider.provider]: fallback }));
    if (typeof (client as Partial<WeatherFlowClient>).providerModels !== "function") return fallback;
    const catalog = await client.providerModels(provider.provider);
    setCatalogs((current) => ({ ...current, [provider.provider]: catalog.models }));
    return catalog.models;
  }, [client]);

  useEffect(() => {
    if (!preset || !credentialPresent) return;
    void loadModels(preset).catch(() => {
      setConfigureError("这个密钥暂时无法刷新模型目录；可以重新输入密钥后再试。");
    });
  }, [credentialPresent, loadModels, preset]);

  useEffect(() => {
    const summaryClient = client as Partial<WeatherFlowClient>;
    if (section !== "system" || typeof summaryClient.watchSummarySettings !== "function") return;
    let current = true;
    setSummaryLoading(true);
    setSummaryError(null);
    void client.watchSummarySettings().then(async (settings) => {
      if (!current) return;
      const currentProvider = system?.model?.configured ? system.model.provider : null;
      const currentModel = system?.model?.configured ? system.model.model : null;
      const summaryProvider = currentProvider;
      const configuredModel = settings.provider === currentProvider
        ? settings.model ?? currentModel
        : currentModel;
      setSummarySettings(settings);
      setSummaryModel(configuredModel ?? "");
      let models: ProviderModel[] = [];
      const provider = providers.find((item) => item.provider === summaryProvider);
      if (provider) models = presetModelOptions(provider);
      if (summaryProvider && typeof summaryClient.providerModels === "function") {
        try {
          models = (await client.providerModels(summaryProvider)).models;
        } catch {
          // The saved model remains usable even when the provider catalog is temporarily unavailable.
        }
      }
      if (configuredModel && !models.some((item) => item.id === configuredModel)) {
        models = [{ id: configuredModel, selectable: true, compatibility: "agent_ready", note: "当前配置" }, ...models];
      }
      if (current) setSummaryModels(models);
    }).catch(() => {
      if (current) setSummaryError("暂时无法读取最近总结设置，请确认本机服务已恢复后重试。");
    }).finally(() => {
      if (current) setSummaryLoading(false);
    });
    return () => { current = false; };
  }, [client, providers, section, system?.model?.configured, system?.model?.model, system?.model?.provider]);

  const chooseProvider = (provider: ModelProviderPreset) => {
    setSelectedProvider(provider.provider);
    setModel(system?.model?.provider === provider.provider && system.model.model ? system.model.model : provider.default_model);
    setBillingOrigin(system?.model?.provider === provider.provider ? system.model.billing_origin ?? "" : "");
    setModelSearch(""); setApiKey(""); setEditingKey(false); setConfigureError(null);
  };

  const configure = async (event: FormEvent) => {
    event.preventDefault();
    if (!preset || !workspaceId || configuring || !apiKey.trim()) return;
    setConfiguring(true); setConfigureError(null);
    try {
      await nativeCredentials.set(selectedProvider as CredentialProvider, apiKey.trim());
      let models = presetModelOptions(preset);
      try { models = await loadModels(preset); } catch { /* configure verifies the selected model */ }
      const selectedModel = models.some((item) => item.id === model && item.selectable)
        ? model
        : models.some((item) => item.id === preset.default_model && item.selectable)
          ? preset.default_model
          : models.find((item) => item.selectable)?.id ?? preset.default_model;
      await client.configureModel({
        provider: selectedProvider,
        model: selectedModel,
        base_url: preset.base_url,
        ...(selectedProvider === "minimax" ? { billing_origin: billingOrigin || null } : {}),
      }, workspaceId);
      setApiKey(""); setEditingKey(false); setModel(selectedModel);
      setCredentialStatus((current) => ({ ...current, [selectedProvider]: true }));
      await onModelChanged();
      onOperation(`${preset.label} 已启用，密钥由 WeatherFlow 安全保存。`);
    } catch {
      setConfigureError("验证或保存失败，请检查 API Key、账户额度和网络后重试。");
    } finally { setConfiguring(false); }
  };

  const activateModel = async (nextModel: string) => {
    if (!preset || !workspaceId || configuring || !credentialPresent) return;
    setConfiguring(true); setConfigureError(null);
    try {
      await client.configureModel({
        provider: selectedProvider,
        model: nextModel,
        base_url: preset.base_url,
        ...(selectedProvider === "minimax" ? {
          billing_origin: billingOrigin
            || (system?.model?.provider === selectedProvider ? system.model.billing_origin : null)
            || null,
        } : {}),
      }, workspaceId);
      setModel(nextModel);
      await onModelChanged();
      onOperation(`已切换到 ${nextModel}，后续对话将使用这个模型。`);
    } catch {
      setConfigureError("模型切换失败，请检查该模型是否对当前 API Key 开放。");
    } finally { setConfiguring(false); }
  };

  const deleteCredential = async () => {
    if (!preset || configuring) return;
    setConfiguring(true); setConfigureError(null);
    try {
      await nativeCredentials.delete(selectedProvider as CredentialProvider);
      setApiKey(""); setEditingKey(false);
      setCredentialStatus((current) => ({ ...current, [selectedProvider]: false }));
      onOperation(`${preset.label} 的 API Key 已从 WeatherFlow 删除。`);
    } catch {
      setConfigureError("暂时无法删除密钥，请稍后重试。");
    } finally { setConfiguring(false); }
  };

  const exportDiagnostics = async () => { const result = await client.exportDiagnostics(workspaceId); onOperation(`诊断文件已保存到本机：${result.path}`); };
  const reviewReset = async () => onResetPreview(await client.previewReset("activity", workspaceId));
  const reset = async () => { const result = await client.reset("activity", workspaceId); onResetPreview(null); onOperation(`已删除 ${result.deleted_count} 条活动总结记录。`); };
  const chooseTheme = (preference: ThemePreference) => {
    setThemePreference(preference);
    setTheme(preference);
  };

  const saveSummarySettings = async (event: FormEvent) => {
    event.preventDefault();
    if (!summarySettings || !summaryModel || summarySaving) return;
    setSummarySaving(true);
    setSummaryError(null);
    try {
      const updated = await client.updateWatchSummarySettings({
        model_workspace_id: workspaceId ?? summarySettings.model_workspace_id,
        model: summaryModel,
        expected_version: summarySettings.version,
      });
      setSummarySettings(updated);
      setSummaryModel(updated.model ?? summaryModel);
      onOperation("最近总结设置已保存；后续生成或重新生成会使用新配置。");
    } catch {
      setSummaryError("保存失败；设置可能已在别处更新，请重新打开设置后再试。");
    } finally {
      setSummarySaving(false);
    }
  };

  if (section === "system") return <div className="page-view settings-view system-settings-view">
    <header className="page-header"><span>设置</span><h1>外观、本机与隐私</h1><p>调整 WeatherFlow 的显示方式，并管理可删除的数据与诊断信息。</p></header>
    <section className="settings-section appearance-section"><div className="section-title"><h2>界面主题</h2><p>选择浅色、深色，或自动跟随 macOS 外观。</p></div><div className="theme-options" role="radiogroup" aria-label="界面主题">{([
      ["system", "跟随系统", "随 macOS 自动切换", <Desktop weight="duotone" />],
      ["light", "浅色", "明亮、清晰的工作区", <Sun weight="duotone" />],
      ["dark", "深色", "低光环境更舒适", <Moon weight="duotone" />],
    ] as const).map(([value, label, note, icon]) => <button key={value} type="button" role="radio" aria-label={label} aria-checked={theme === value} onClick={() => chooseTheme(value)}><i aria-hidden="true">{icon}</i><span><strong>{label}</strong><small>{note}</small></span>{theme === value && <Check weight="bold" />}</button>)}</div></section>
    <section className="settings-section summary-settings-section">
      <div className="section-title"><h2>最近总结</h2><p>选择后续活动总结使用的模型。总结规则由 WeatherFlow 固定，所有生成内容统一使用简体中文。</p></div>
      {summaryLoading ? <p className="summary-settings-loading">正在读取设置…</p> : summarySettings ? <form className="summary-settings-form" onSubmit={saveSummarySettings}>
        <label>模型<select aria-label="最近总结模型" value={summaryModel} onChange={(event) => setSummaryModel(event.target.value)} disabled={summarySaving}>{summaryModels.filter((item) => item.selectable).map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
        <p>内置规则会分别纳入 ActivityWatch 与 GitHub、Gmail、Google Calendar 的有界只读快照；外部原文始终是不可信数据。规则版本：<code>{summarySettings.prompt_version}</code></p>
        {summaryError && <p className="form-error" role="alert">{summaryError}</p>}
        <button type="submit" className="primary" disabled={summarySaving || !summaryModel}>{summarySaving ? "正在保存…" : "保存最近总结设置"}</button>
      </form> : summaryError ? <p className="form-error" role="alert">{summaryError}</p> : null}
    </section>
    <section className="settings-section privacy-section"><div className="section-title"><h2>本机与隐私</h2></div><dl><div><dt>项目</dt><dd>{snapshot?.workspace.action_roots[0] ?? "加载中"}</dd></div><div><dt>当前模型</dt><dd>{system?.model?.configured ? `${system.model.provider} · ${system.model.model}` : "尚未配置"}</dd></div><div><dt>活动来源</dt><dd>ActivityWatch 只读 · 独立运行</dd></div><div><dt>本机桥接</dt><dd>{offline ? "正在恢复" : "已认证"}</dd></div></dl><div className="settings-actions"><button onClick={() => void exportDiagnostics()}>导出本机诊断</button>{!resetPreview ? <button onClick={() => void reviewReset()}>检查活动派生历史清理</button> : <button className="danger" onClick={() => void reset()}>删除 {resetPreview.count} 条活动总结记录</button>}</div></section>
  </div>;

  return <div className="page-view settings-view">
    <header className="page-header"><span>LLM 模型</span><h1>选择并配置语言模型提供商</h1><p>一把 API Key 可以访问同一厂商的多个模型。配置一次后保持开启，对话时由你随时切换。</p></header>
    <section className="settings-section model-provider-section">
      <div className="section-title"><h2>LLM 提供商</h2><p>显示 WeatherFlow 已完整适配的国内外厂商；开关表示密钥已由本机安全保存。</p></div>
      {system?.model?.configured && !system.model.credential_available && <div className="settings-warning" role="alert"><strong>模型密钥不可用</strong><span>请重新输入 API Key。WeatherFlow 会直接通过系统安全存储处理，不需要你打开“钥匙串访问”。</span></div>}
      <div className="provider-pills provider-switch-grid">{providers.map((item) => {
        const enabled = credentialStatus[item.provider] ?? (system?.model?.provider === item.provider && Boolean(system.model.credential_available));
        const active = system?.model?.provider === item.provider && Boolean(system.model.configured);
        return <button type="button" role="switch" aria-label={item.label} aria-checked={enabled} className={`${item.provider === selectedProvider ? "selected" : ""} ${active ? "active-model" : ""}`} data-provider={item.provider} key={item.provider} onClick={() => chooseProvider(item)}><span>{item.label}{active && <small>当前</small>}</span><i className="provider-toggle" aria-hidden="true"><b /></i></button>;
      })}</div>
      {preset && <div className="provider-detail" data-provider={preset.provider}>
        <div className="provider-detail-head"><div><span className="eyebrow">{credentialPresent ? "已连接" : "等待配置"}</span><h3>{preset.label}</h3><p>{preset.base_url}</p></div>{credentialPresent && <span className="secure-badge"><ShieldCheck />密钥已保存</span>}</div>
        {(!credentialPresent || editingKey) ? <form className="provider-key-form" onSubmit={configure}><label>API Key<input aria-label="API Key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={`粘贴 ${preset.label} API Key`} /></label>{preset.provider === "minimax" && <label>计费来源<select aria-label="MiniMax 计费来源" value={billingOrigin} onChange={(event) => setBillingOrigin(event.target.value as BillingOrigin | "")}><option value="">未确认（成本保持 unknown）</option>{(preset.billing_origins ?? []).map((origin) => <option key={origin} value={origin}>{billingOriginLabel(origin)}</option>)}</select></label>}<p>{preset.provider === "minimax" ? "API 地址不能证明密钥属于按量计费还是 Token Plan；只有明确选择按量计费后才按对应币种计算模型用量。" : "密钥不会进入 React 状态之外的持久数据、Python 日志、事件、记忆或模型提示词。"}</p>{configureError && <p className="form-error" role="alert">{configureError}</p>}<div><button type="submit" className="primary" disabled={!apiKey.trim() || configuring}>{configuring ? "正在验证…" : `验证并启用 ${preset.label}`}</button>{credentialPresent && <button type="button" onClick={() => { setEditingKey(false); setApiKey(""); }}>取消</button>}</div></form> : <>
          <div className="provider-model-heading"><div><h4>这个密钥可用的语言模型</h4><p>目录来自厂商 API；切换只影响后续模型调用，不做自动路由。</p></div>{availableModels.length > 8 && <input aria-label="搜索模型" type="search" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder="搜索模型…" />}</div>
          <div className="provider-model-list">{visibleModels.map((item) => {
            const active = system?.model?.provider === selectedProvider && system.model.model === item.id;
            return <button type="button" aria-label={`使用 ${item.id}`} className={`${active ? "active" : ""} ${!item.selectable ? "incompatible" : ""}`} disabled={configuring || active || !item.selectable} key={item.id} title={item.note ?? undefined} onClick={() => void activateModel(item.id)}><span>{item.id}{item.note && <small>{item.note}</small>}</span>{active ? <><Check /><small>正在使用</small></> : <small>{item.selectable ? "切换" : "暂不可用"}</small>}</button>;
          })}{visibleModels.length === 0 && <p className="model-list-empty">没有匹配的模型；可更新密钥后重新读取目录。</p>}</div>
          {configureError && <p className="form-error" role="alert">{configureError}</p>}
          <div className="provider-credential-actions"><button type="button" onClick={() => { setEditingKey(true); setConfigureError(null); }}>更新 API Key</button><button type="button" className="danger" onClick={() => void deleteCredential()} disabled={configuring}>删除 API Key</button></div>
        </>}
      </div>}
    </section>
  </div>;
}
