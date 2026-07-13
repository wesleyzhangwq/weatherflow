import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  CalendarBlank, CaretDown, ChatCircleDots, Check, CheckCircle, CloudSun, EnvelopeSimple,
  FolderOpen, GearSix, GithubLogo, ListChecks, PaperPlaneRight, PlugsConnected, Plus,
  Robot, ShieldCheck, Sparkle, Wrench,
} from "@phosphor-icons/react";
import { WeatherFlowClient } from "../bridge";
import { nativeCredentials, nativeWindows, type CredentialProvider } from "../native";
import type {
  Approval, Artifact, ConnectionAttempt, ConnectorKind, ConnectorStatus, DesktopSnapshot,
  LedgerEvent, ModelProviderPreset, ProviderModel, ResetPreview, Run, SystemStatus, Workspace,
} from "../types";

type ViewId = "chat" | "runs" | "rhythm" | "connections" | "settings";

const runStatusText: Record<Run["status"], string> = {
  queued: "已排队", planning: "规划中", running: "执行中", waiting_approval: "等待批准",
  waiting_user: "等待你的输入", paused: "已暂停", needs_review: "需要检查",
  succeeded: "已完成", failed: "失败", cancelled: "已取消",
};
const weatherText = { clear: "晴朗 · 心流", fair: "微晴 · 稳定", fog: "薄雾 · 分散", storm: "风暴 · 过载", still: "静滞 · 受阻", night: "夜色 · 恢复", mixed: "混合 · 待确认" } as const;
const workModeText: Record<string, string> = { normal: "常规协作", focus: "专注推进", recovery: "轻量恢复", overloaded: "减负协作" };
const rhythmSummaryText: Record<string, string> = { "Steady rhythm": "节奏稳定" };
function presetModelOptions(provider: ModelProviderPreset): ProviderModel[] {
  return provider.suggested_models.map((id) => ({
    id, selectable: true, compatibility: "agent_ready", note: null,
  }));
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
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const refreshGeneration = useRef(0);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [timeline, setTimeline] = useState<LedgerEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [providers, setProviders] = useState<ModelProviderPreset[]>([]);
  const [resetPreview, setResetPreview] = useState<ResetPreview | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [rhythmText, setRhythmText] = useState("");
  const [rhythmKind, setRhythmKind] = useState<"checkin" | "correction">("checkin");
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const run = useMemo(() => runs.find((item) => item.id === selectedRunId) ?? runs[0] ?? snapshot?.latest_run ?? null, [runs, selectedRunId, snapshot]);
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
      const [events, files] = await Promise.all([client.timeline(activeId), client.artifacts(activeId)]);
      if (generation !== refreshGeneration.current) return;
      setTimeline(events); setArtifacts(files);
    } else { setTimeline([]); setArtifacts([]); }
  }, [client, selectedWorkspaceId]);

  useEffect(() => { void refresh(); }, [refresh, snapshot]);
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
      const accepted = await client.createRun(intent, crypto.randomUUID(), selectedWorkspaceId, run?.id);
      selectedRunIdRef.current = accepted.id;
      setSelectedRunId(accepted.id);
      setRuns((current) => [accepted, ...current.filter((item) => item.id !== accepted.id)]);
      setChatInput("");
      await refresh(accepted.id);
    } finally { setSending(false); }
  };
  const selectRun = (runId: string) => {
    selectedRunIdRef.current = runId;
    setSelectedRunId(runId);
    void refresh(runId);
  };
  const decide = async (approval: Approval, decision: "approve" | "deny") => {
    await client.decide(approval.id, decision, approval.version); await refresh();
  };
  const chooseWorkspace = async () => {
    const path = await nativeWindows.chooseWorkspaceDirectory();
    if (!path || !onAuthorizeWorkspace) return;
    const workspace = await onAuthorizeWorkspace(path);
    setOperation(`已授权项目 ${workspace.name}：${workspace.action_roots[0]}`);
  };
  const submitRhythm = async (event: FormEvent) => {
    event.preventDefault(); const text = rhythmText.trim(); if (!text) return;
    await client.ingestSignal({ kind: rhythmKind, text, observed_at: new Date().toISOString() }, selectedWorkspaceId);
    setRhythmText(""); setOperation(rhythmKind === "correction" ? "已用你的修正更新当前判断。" : "已记录本次状态签到。"); await refresh();
  };
  const downloadArtifact = async (artifact: Artifact) => {
    const blob = await client.artifactContent(artifact.id); const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.name; anchor.click(); URL.revokeObjectURL(url);
  };

  return (
    <main className="cockpit-shell">
      <aside className="app-sidebar">
        <div className="brand"><Sparkle size={22} weight="fill" /><div><strong>WeatherFlow</strong><small>个人智能体</small></div></div>
        <nav aria-label="主导航">
          <NavButton active={view === "chat"} icon={<ChatCircleDots />} label="对话" onClick={() => setView("chat")} />
          <NavButton active={view === "runs"} icon={<ListChecks />} label="任务" badge={pending.length || undefined} onClick={() => setView("runs")} />
          <NavButton active={view === "rhythm"} icon={<CloudSun />} label="状态天气" onClick={() => setView("rhythm")} />
          <NavButton active={view === "connections"} icon={<PlugsConnected />} label="连接" onClick={() => setView("connections")} />
          <NavButton active={view === "settings"} icon={<GearSix />} label="设置" onClick={() => setView("settings")} />
        </nav>
        <div className="sidebar-project">
          <select aria-label="当前项目" value={selectedWorkspaceId ?? ""} onChange={(event) => onSelectWorkspace?.(event.target.value)}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select>
          <button onClick={() => void chooseWorkspace()}><FolderOpen /> 添加项目</button>
        </div>
        <div className={`local-status ${offline ? "offline" : ""}`}><i />{offline ? "内核离线" : "本机运行 · 数据私有"}</div>
      </aside>

      <section className="app-workspace">
        {view === "chat" && <ChatView client={client} providers={providers} workspaceId={selectedWorkspaceId} runs={runs} run={run} pending={pending} artifacts={artifacts} chatInput={chatInput} sending={sending} workspaceReady={Boolean(selectedWorkspaceId)} snapshot={snapshot} system={system} onInput={setChatInput} onSubmit={submitChat} onSelectRun={selectRun} onDecide={decide} onDownload={downloadArtifact} onModelChanged={refresh} onOpenSettings={() => setView("settings")} />}
        {view === "runs" && <RunsView runs={runs} run={run} timeline={timeline} artifacts={artifacts} pending={pending} onSelect={selectRun} onDecide={decide} onDownload={downloadArtifact} />}
        {view === "rhythm" && <RhythmView snapshot={snapshot} rhythmKind={rhythmKind} rhythmText={rhythmText} onKind={setRhythmKind} onText={setRhythmText} onSubmit={submitRhythm} />}
        {view === "connections" && <ConnectionsView client={client} workspaceId={selectedWorkspaceId} onOperation={setOperation} />}
        {view === "settings" && <SettingsView client={client} system={system} providers={providers} workspaceId={selectedWorkspaceId} offline={offline} snapshot={snapshot} resetPreview={resetPreview} onResetPreview={setResetPreview} onOperation={setOperation} onModelChanged={refresh} />}
        {operation && <div className="operation-toast" role="status">{operation}</div>}
      </section>
    </main>
  );
}

function NavButton({ active, icon, label, badge, onClick }: { active: boolean; icon: React.ReactElement; label: string; badge?: number; onClick: () => void }) {
  return <button className={active ? "active" : ""} aria-label={label} onClick={onClick}>{icon}<span>{label}</span>{badge && <b>{badge}</b>}</button>;
}

function ChatView({ client, providers, workspaceId, runs, run, pending, artifacts, chatInput, sending, workspaceReady, snapshot, system, onInput, onSubmit, onSelectRun, onDecide, onDownload, onModelChanged, onOpenSettings }: { client: WeatherFlowClient; providers: ModelProviderPreset[]; workspaceId?: string | null; runs: Run[]; run: Run | null; pending: Approval[]; artifacts: Artifact[]; chatInput: string; sending: boolean; workspaceReady: boolean; snapshot: DesktopSnapshot | null; system: SystemStatus | null; onInput: (value: string) => void; onSubmit: (event: FormEvent) => void; onSelectRun: (id: string) => void; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void; onModelChanged: () => Promise<void>; onOpenSettings: () => void }) {
  const scene = snapshot?.rhythm.weather.scene ?? "mixed";
  const composing = useRef(false);
  return <div className="chat-layout">
    <section className="conversation-pane">
      <header className="workspace-header">
        <div><span>对话</span><h1>今天想一起推进什么？</h1></div>
        <div className="conversation-signals">
          <div className="signal-chip weather" aria-label="人的状态天气" data-scene={scene}><CloudSun /><span><small>你的天气</small>{weatherText[scene]}</span></div>
          <div className="signal-chip task" aria-label="智能体任务状态"><span className={`run-dot ${run?.status ?? "idle"}`} /><span><small>当前任务</small>{run ? runStatusText[run.status] : "空闲"}</span></div>
        </div>
      </header>
      <div className="conversation-scroll">
        {runs.length === 0 && <div className="chat-empty"><div className="empty-icon"><ChatCircleDots size={30} /></div><p className="eyebrow">从对话开始</p><h2>说出你真正想完成的事</h2><p>WeatherFlow 会结合你的状态调整协作方式，在后台保存任务进度，只在需要决定时打断你。</p><div className="empty-promises"><span><ShieldCheck /> 关键操作先批准</span><span><CheckCircle /> 任务进度可恢复</span></div></div>}
        {[...runs].reverse().map((item) => <article className={`conversation-turn ${item.id === run?.id ? "selected" : ""}`} key={item.id}>
          <button className="conversation-select" aria-label={`查看任务：${item.user_intent}`} onClick={() => onSelectRun(item.id)}>
            <span className="message-label">你</span><div className="user-message">{item.user_intent}</div>
            <div className="assistant-message"><span className="message-label">WeatherFlow</span><p>{runMessage(item)}</p><small><span className={`run-dot ${item.status}`} />{runStatusText[item.status]} · {formatRelativeTime(item.updated_at)}</small></div>
          </button>
        </article>)}
      </div>
      <form className="chat-composer" onSubmit={(event) => { if (composing.current) { event.preventDefault(); return; } onSubmit(event); }}><button type="button" aria-label="添加附件"><Plus /></button><textarea aria-label="对话输入" rows={1} value={chatInput} onChange={(event) => onInput(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229 && !composing.current) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={workspaceReady ? "给 WeatherFlow 发消息…" : "先在左下角选择或添加项目"} /><button className="send-button" aria-label="发送" disabled={sending || !workspaceReady || !chatInput.trim()}><PaperPlaneRight weight="fill" /></button></form>
      <footer className="composer-meta">{workspaceReady ? <ModelSwitcher client={client} providers={providers} workspaceId={workspaceId} system={system} disabled={sending} onChanged={onModelChanged} onOpenSettings={onOpenSettings} /> : <span>先选择或添加一个项目，才能开始任务</span>}<span>Enter 发送 · Shift + Enter 换行</span></footer>
    </section>
    <aside className="chat-context"><div className="context-heading"><Wrench /><span>当前上下文</span></div><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside>
  </div>;
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
      await client.configureModel({ provider: provider.provider, model, base_url: provider.base_url }, workspaceId);
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

function RunsView({ runs, run, timeline, artifacts, pending, onSelect, onDecide, onDownload }: { runs: Run[]; run: Run | null; timeline: LedgerEvent[]; artifacts: Artifact[]; pending: Approval[]; onSelect: (id: string) => void; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <div className="page-view"><header className="page-header"><span>任务</span><h1>执行、批准与产出</h1><p>这里展示智能体的工作状态；你的状态天气始终独立，不会被任务成败覆盖。</p></header><div className="runs-layout"><nav className="run-list" aria-label="任务列表">{runs.length === 0 ? <div className="run-list-empty">暂无任务</div> : runs.map((item) => <button className={item.id === run?.id ? "selected" : ""} key={item.id} onClick={() => onSelect(item.id)} aria-pressed={item.id === run?.id} aria-label={`${item.user_intent}，${runStatusText[item.status]}`}><span>{item.user_intent}</span><small><i className={`run-dot ${item.status}`} />{runStatusText[item.status]} · {formatRelativeTime(item.updated_at)}</small></button>)}</nav><section className="run-detail">{run ? <><div className="run-detail-heading"><span className={`status-pill ${run.status}`}>{runStatusText[run.status]}</span><time>{formatRelativeTime(run.updated_at)}</time></div><h2>{run.user_intent}</h2><div className="run-result"><span>当前结果</span><p>{runMessage(run)}</p></div><div className="section-heading"><h3>执行记录</h3><small>{timeline.length} 个事件</small></div>{timeline.length ? <ol className="timeline">{timeline.slice(-12).reverse().map((event) => <li key={event.id}><i /><div><strong>{formatEventType(event.type)}</strong><time>{new Date(event.recorded_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div></li>)}</ol> : <div className="detail-empty">等待第一条执行记录</div>}</> : <div className="detail-empty centered">选择一个任务查看完整执行记录</div>}</section><aside className="run-context"><div className="context-heading"><Wrench /><span>任务上下文</span></div><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside></div></div>;
}

function RhythmView({ snapshot, rhythmKind, rhythmText, onKind, onText, onSubmit }: { snapshot: DesktopSnapshot | null; rhythmKind: "checkin" | "correction"; rhythmText: string; onKind: (value: "checkin" | "correction") => void; onText: (value: string) => void; onSubmit: (event: FormEvent) => void }) {
  const scene = snapshot?.rhythm.weather.scene ?? "mixed";
  const intensity = Math.round((snapshot?.rhythm.weather.intensity ?? 0) * 100);
  const rawSummary = snapshot?.rhythm.snapshot.summary;
  const summary = rawSummary ? rhythmSummaryText[rawSummary] ?? rawSummary : "等待你的第一次签到";
  const rawWorkMode = snapshot?.rhythm.policy.work_mode;
  const workMode = rawWorkMode ? workModeText[rawWorkMode] ?? rawWorkMode : "等待判断";
  return <div className="page-view rhythm-view"><header className="page-header"><span>状态天气</span><h1>WeatherFlow 现在如何理解你</h1><p>天气只改变协作的节奏、提问频率和输出密度，不会改变你的目标。</p></header><div className="rhythm-content"><section className="rhythm-hero" data-scene={scene}><div className="rhythm-weather-icon"><CloudSun size={48} /></div><div className="rhythm-summary"><small>当前天气</small><h2>{weatherText[scene]}</h2><p>{summary}</p></div><dl><div><dt>协作模式</dt><dd>{workMode}</dd></div><div><dt>天气强度</dt><dd>{intensity}%</dd></div><div><dt>有效至</dt><dd>{snapshot ? new Date(snapshot.rhythm.snapshot.valid_until).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</dd></div></dl></section><section className="rhythm-checkin"><div><span className="eyebrow">主动信号</span><h2>{rhythmKind === "correction" ? "修正 WeatherFlow 的判断" : "告诉 WeatherFlow 你现在的真实状态"}</h2><p>{rhythmKind === "correction" ? "你的修正优先于自动推断。" : "一句自然语言就够了，例如“今天有点过载，先帮我收窄任务”。"}</p></div><form className="rhythm-form-large" onSubmit={onSubmit}><div className="segmented-control" role="group" aria-label="状态信号类型"><button type="button" className={rhythmKind === "checkin" ? "selected" : ""} aria-pressed={rhythmKind === "checkin"} onClick={() => onKind("checkin")}>主动签到</button><button type="button" className={rhythmKind === "correction" ? "selected" : ""} aria-pressed={rhythmKind === "correction"} onClick={() => onKind("correction")}>修正判断</button></div><textarea aria-label="状态签到" value={rhythmText} onChange={(event) => onText(event.target.value)} placeholder="你现在真实的状态怎么样？" /><button className="primary" disabled={!rhythmText.trim()}>保存状态</button></form></section></div></div>;
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
    return "无法读取模型密钥，请到“设置”重新粘贴 API Key。";
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
  github: { note: "与你相关的 Issue、Pull Request 与账号信息", icon: <GithubLogo weight="fill" /> },
  gmail: { note: "未读邮件的标题、发件人与摘要", icon: <EnvelopeSimple weight="fill" /> },
  google_calendar: { note: "未来 14 天的日程与时间安排", icon: <CalendarBlank weight="fill" /> },
};

function ConnectionsView({ client, workspaceId, onOperation }: { client: WeatherFlowClient; workspaceId?: string | null; onOperation: (value: string) => void }) {
  const [statuses, setStatuses] = useState<ConnectorStatus[]>([]);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<ConnectorKind | "configure" | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<ConnectorKind | null>(null);
  const [handoffs, setHandoffs] = useState<Partial<Record<ConnectorKind, string>>>({});
  const connecting = useRef(new Set<ConnectorKind>());
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    if (!workspaceId) return;
    setStatuses(await client.connectors(workspaceId));
  }, [client, workspaceId]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  const configured = statuses.some((status) => status.configured);
  const configure = async (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim() || busy) return;
    setBusy("configure");
    try {
      await nativeCredentials.set("composio", apiKey.trim());
      await client.configureConnectors();
      setApiKey("");
      await refresh();
      onOperation("Composio 项目密钥已验证并保存到本机钥匙串。");
    } catch {
      onOperation("Composio 密钥验证失败，请检查项目密钥与网络连接。");
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
          onOperation("连接成功，自动抓取已开启。");
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
      onOperation("无法启动连接；如果授权页已生成，可点击“重新打开授权页”。");
    } finally { setBusy(null); }
  };

  const updateSettings = async (status: ConnectorStatus, autoFetchEnabled: boolean, intervalMinutes = status.interval_minutes) => {
    if (!workspaceId) return;
    setBusy(status.connector);
    try {
      await client.updateConnectorSettings(status.connector, autoFetchEnabled, intervalMinutes, workspaceId);
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
      await client.disconnectConnector(status.connector);
      setConfirmDisconnect(null);
      await refresh();
      onOperation(`${status.label} 已断开，WeatherFlow 本地保存的该连接摘要也已删除。`);
    } finally { setBusy(null); }
  };

  return <div className="page-view connections-view">
    <header className="page-header"><span>连接</span><h1>Composio Direct 连接</h1><p>只开放 GitHub、Gmail 和 Google Calendar 的固定只读抓取。服务商 OAuth 令牌由 Composio 托管；WeatherFlow 只把项目密钥保存在 macOS 钥匙串，并在本机保存摘要。</p></header>
    {!configured ? <form className="connector-key-form" onSubmit={configure}><div><h2>先连接你的 Composio 项目</h2><p>使用 scoped project API key。密钥不会进入对话、日志、事件、记忆或产出文件。</p></div><label>Composio Project API Key<input aria-label="Composio Project API Key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="cmp_…" /></label><button className="primary" disabled={!apiKey.trim() || busy === "configure"}>验证并保存连接密钥</button></form> : <div className="credential-summary"><span><ShieldCheck size={18} />Composio 密钥已由 WeatherFlow 安全保存</span><button type="button" onClick={() => void removeCredential()} disabled={Boolean(busy)}>删除密钥</button></div>}
    <div className="connection-grid">{statuses.map((status) => {
      const presentation = connectorPresentation[status.connector];
      const isBusy = busy === status.connector;
      const isWaiting = Boolean(status.attempt_id && status.attempt_expires_at);
      return <article className={status.connected ? "connected" : ""} key={status.connector}>
        <div className="connector-card-head"><div className={`service-mark ${status.connector}`}>{presentation.icon}</div><span className={`connection-state ${status.connected ? "active" : ""}`}>{status.connected ? "已连接" : isWaiting ? "等待授权" : "未连接"}</span></div>
        <h2>{status.label}</h2><p>{presentation.note}</p>
        {status.connected ? <>
          <strong className="connector-account">{status.display_name || "授权账号"}</strong>
          <label className="connector-toggle"><input type="checkbox" checked={status.auto_fetch_enabled} onChange={(event) => void updateSettings(status, event.target.checked)} disabled={isBusy} /><span>自动抓取</span></label>
          <label className="connector-interval">抓取频率<select aria-label={`${status.label} 抓取频率`} value={status.interval_minutes} onChange={(event) => void updateSettings(status, status.auto_fetch_enabled, Number(event.target.value))} disabled={isBusy}><option value={15}>每 15 分钟</option><option value={60}>每小时</option><option value={240}>每 4 小时</option><option value={1440}>每天</option></select></label>
          <small>{status.last_sync_at ? `上次抓取 ${new Date(status.last_sync_at).toLocaleString("zh-CN")}` : "尚未完成首次抓取"}</small>
          <div className="connector-actions"><button onClick={() => void sync(status)} disabled={isBusy}>立即抓取</button>{confirmDisconnect === status.connector ? <button className="danger" onClick={() => void disconnect(status)} disabled={isBusy}>确认断开并删除摘要</button> : <button onClick={() => setConfirmDisconnect(status.connector)}>断开连接</button>}</div>
        </> : <>
          <span>通过系统浏览器完成 OAuth 授权</span>
          <button className="connect-button" onClick={() => void connect(status.connector, status.label)} disabled={!configured || isBusy || isWaiting || connecting.current.has(status.connector)} aria-label={`连接 ${status.label}`}>{isWaiting ? "等待浏览器授权…" : `连接 ${status.label}`}</button>
          {handoffs[status.connector] && <button className="link-button" onClick={() => void nativeWindows.openConnectorUrl(handoffs[status.connector]!)}>重新打开授权页</button>}
        </>}
      </article>;
    })}</div>
  </div>;
}

function SettingsView({ client, system, providers, workspaceId, offline, snapshot, resetPreview, onResetPreview, onOperation, onModelChanged }: { client: WeatherFlowClient; system: SystemStatus | null; providers: ModelProviderPreset[]; workspaceId?: string | null; offline: boolean; snapshot: DesktopSnapshot | null; resetPreview: ResetPreview | null; onResetPreview: (value: ResetPreview | null) => void; onOperation: (value: string) => void; onModelChanged: () => Promise<void> }) {
  const [selectedProvider, setSelectedProvider] = useState(system?.model?.provider ?? "minimax");
  const [credentialStatus, setCredentialStatus] = useState<Record<string, boolean>>({});
  const [catalogs, setCatalogs] = useState<Record<string, ProviderModel[]>>({});
  const [model, setModel] = useState(system?.model?.model ?? "MiniMax-M3");
  const [modelSearch, setModelSearch] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [editingKey, setEditingKey] = useState(false);
  const [configureError, setConfigureError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState(false);
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
    }
  }, [system?.model?.configured, system?.model?.model, system?.model?.provider]);

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

  const chooseProvider = (provider: ModelProviderPreset) => {
    setSelectedProvider(provider.provider);
    setModel(system?.model?.provider === provider.provider && system.model.model ? system.model.model : provider.default_model);
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
      await client.configureModel({ provider: selectedProvider, model: selectedModel, base_url: preset.base_url }, workspaceId);
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
      await client.configureModel({ provider: selectedProvider, model: nextModel, base_url: preset.base_url }, workspaceId);
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
  const reviewReset = async () => onResetPreview(await client.previewReset("behavior", workspaceId));
  const reset = async () => { const result = await client.reset("behavior", workspaceId); onResetPreview(null); onOperation(`已删除 ${result.deleted_count} 条行为记录。`); };

  return <div className="page-view settings-view">
    <header className="page-header"><span>设置</span><h1>选择并配置语言模型提供商</h1><p>一把 API Key 可以访问同一厂商的多个模型。配置一次后保持开启，对话时由你随时切换。</p></header>
    <section className="settings-section model-provider-section">
      <div className="section-title"><h2>LLM 提供商</h2><p>只显示 WeatherFlow 已适配的国内常用厂商；开关表示密钥已由本机安全保存。</p></div>
      {system?.model?.configured && !system.model.credential_available && <div className="settings-warning" role="alert"><strong>模型密钥不可用</strong><span>请重新输入 API Key。WeatherFlow 会直接通过系统安全存储处理，不需要你打开“钥匙串访问”。</span></div>}
      <div className="provider-pills provider-switch-grid">{providers.map((item) => {
        const enabled = credentialStatus[item.provider] ?? (system?.model?.provider === item.provider && Boolean(system.model.credential_available));
        const active = system?.model?.provider === item.provider && Boolean(system.model.configured);
        return <button type="button" role="switch" aria-label={item.label} aria-checked={enabled} className={`${item.provider === selectedProvider ? "selected" : ""} ${active ? "active-model" : ""}`} data-provider={item.provider} key={item.provider} onClick={() => chooseProvider(item)}><span>{item.label}{active && <small>当前</small>}</span><i className="provider-toggle" aria-hidden="true"><b /></i></button>;
      })}</div>
      {preset && <div className="provider-detail" data-provider={preset.provider}>
        <div className="provider-detail-head"><div><span className="eyebrow">{credentialPresent ? "已连接" : "等待配置"}</span><h3>{preset.label}</h3><p>{preset.base_url}</p></div>{credentialPresent && <span className="secure-badge"><ShieldCheck />密钥已保存</span>}</div>
        {(!credentialPresent || editingKey) ? <form className="provider-key-form" onSubmit={configure}><label>API Key<input aria-label="API Key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={`粘贴 ${preset.label} API Key`} /></label><p>密钥不会进入 React 状态之外的持久数据、Python 日志、事件、记忆或模型提示词。</p>{configureError && <p className="form-error" role="alert">{configureError}</p>}<div><button type="submit" className="primary" disabled={!apiKey.trim() || configuring}>{configuring ? "正在验证…" : `验证并启用 ${preset.label}`}</button>{credentialPresent && <button type="button" onClick={() => { setEditingKey(false); setApiKey(""); }}>取消</button>}</div></form> : <>
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
    <section className="settings-section privacy-section"><div className="section-title"><h2>本机与隐私</h2></div><dl><div><dt>项目</dt><dd>{snapshot?.workspace.action_roots[0] ?? "加载中"}</dd></div><div><dt>当前模型</dt><dd>{system?.model?.configured ? `${system.model.provider} · ${system.model.model}` : "尚未配置"}</dd></div><div><dt>行为感知</dt><dd>{system?.behavior_sensor.enabled ? "已启用元数据" : "仅主动签到"}</dd></div><div><dt>本机桥接</dt><dd>{offline ? "正在恢复" : "已认证"}</dd></div></dl><div className="settings-actions"><button onClick={() => void exportDiagnostics()}>导出本机诊断</button>{!resetPreview ? <button onClick={() => void reviewReset()}>检查行为数据清理</button> : <button className="danger" onClick={() => void reset()}>删除 {resetPreview.count} 条行为记录</button>}</div></section>
  </div>;
}
