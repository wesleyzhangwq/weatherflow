import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  CalendarBlank, ChatCircleDots, CloudSun, EnvelopeSimple, FolderOpen, GearSix,
  GithubLogo, ListChecks, PaperPlaneRight, PlugsConnected, Plus, Sparkle, Wrench,
} from "@phosphor-icons/react";
import { WeatherFlowClient } from "../bridge";
import { nativeWindows } from "../native";
import type {
  Approval, Artifact, DesktopSnapshot, LedgerEvent, ModelProviderPreset,
  ResetPreview, Run, SystemStatus, Workspace,
} from "../types";

type ViewId = "chat" | "runs" | "rhythm" | "connections" | "settings";

const runStatusText: Record<Run["status"], string> = {
  queued: "已排队", planning: "规划中", running: "执行中", waiting_approval: "等待批准",
  waiting_user: "等待你的输入", paused: "已暂停", needs_review: "需要检查",
  succeeded: "已完成", failed: "失败", cancelled: "已取消",
};
const weatherText = { clear: "晴朗 · 心流", fair: "微晴 · 稳定", fog: "薄雾 · 分散", storm: "风暴 · 过载", still: "静滞 · 受阻", night: "夜色 · 恢复", mixed: "混合 · 待确认" } as const;

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

  const refresh = useCallback(async () => {
    const [nextApprovals, status, recent] = await Promise.all([
      client.approvals(), client.status(selectedWorkspaceId), client.runs(selectedWorkspaceId),
    ]);
    setRuns(recent);
    setApprovals(nextApprovals.filter((approval) => recent.some((item) => item.id === approval.run_id)));
    setSystem(status);
    const activeId = selectedRunId && recent.some((item) => item.id === selectedRunId) ? selectedRunId : recent[0]?.id;
    setSelectedRunId(activeId ?? null);
    if (activeId) {
      const [events, files] = await Promise.all([client.timeline(activeId), client.artifacts(activeId)]);
      setTimeline(events); setArtifacts(files);
    } else { setTimeline([]); setArtifacts([]); }
  }, [client, selectedRunId, selectedWorkspaceId]);

  useEffect(() => { void refresh(); }, [refresh, snapshot?.latest_run?.updated_at]);
  useEffect(() => {
    if (view === "settings" && providers.length === 0 && client.modelProviders) {
      void client.modelProviders().then((items) => setProviders(items));
    }
  }, [client, providers.length, view]);

  const submitChat = async (event: FormEvent) => {
    event.preventDefault();
    const intent = chatInput.trim();
    if (!intent || !selectedWorkspaceId || sending) return;
    setSending(true); setOperation(null);
    try {
      await client.createRun(intent, crypto.randomUUID(), selectedWorkspaceId, run?.id);
      setChatInput("");
      await refresh();
    } finally { setSending(false); }
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
        {view === "chat" && <ChatView runs={runs} run={run} pending={pending} artifacts={artifacts} chatInput={chatInput} sending={sending} onInput={setChatInput} onSubmit={submitChat} onSelectRun={setSelectedRunId} onDecide={decide} onDownload={downloadArtifact} />}
        {view === "runs" && <RunsView runs={runs} run={run} timeline={timeline} artifacts={artifacts} pending={pending} onSelect={setSelectedRunId} onDecide={decide} onDownload={downloadArtifact} />}
        {view === "rhythm" && <RhythmView snapshot={snapshot} rhythmKind={rhythmKind} rhythmText={rhythmText} onKind={setRhythmKind} onText={setRhythmText} onSubmit={submitRhythm} />}
        {view === "connections" && <ConnectionsView />}
        {view === "settings" && <SettingsView client={client} system={system} providers={providers} workspaceId={selectedWorkspaceId} offline={offline} snapshot={snapshot} resetPreview={resetPreview} onResetPreview={setResetPreview} onOperation={setOperation} />}
        {operation && <div className="operation-toast" role="status">{operation}</div>}
      </section>
    </main>
  );
}

function NavButton({ active, icon, label, badge, onClick }: { active: boolean; icon: React.ReactElement; label: string; badge?: number; onClick: () => void }) {
  return <button className={active ? "active" : ""} onClick={onClick}>{icon}<span>{label}</span>{badge && <b>{badge}</b>}</button>;
}

function ChatView({ runs, run, pending, artifacts, chatInput, sending, onInput, onSubmit, onSelectRun, onDecide, onDownload }: { runs: Run[]; run: Run | null; pending: Approval[]; artifacts: Artifact[]; chatInput: string; sending: boolean; onInput: (value: string) => void; onSubmit: (event: FormEvent) => void; onSelectRun: (id: string) => void; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <div className="chat-layout">
    <section className="conversation-pane">
      <header className="workspace-header"><div><span>对话</span><h1>今天想让 WeatherFlow 帮你做什么？</h1></div><small>⌘⇧Space 随时唤出快捷输入</small></header>
      <div className="conversation-scroll">
        {runs.length === 0 && <div className="chat-empty"><ChatCircleDots size={38} /><h2>从一条消息开始</h2><p>它会结合你的状态，在后台调用工具、保存进度，并把需要决定的事情留给你。</p></div>}
        {[...runs].reverse().map((item) => <article className="conversation-turn" key={item.id} onClick={() => onSelectRun(item.id)}>
          <div className="user-message">{item.user_intent}</div>
          <div className="assistant-message"><span className={`run-dot ${item.status}`} />{item.result_summary ?? `任务${runStatusText[item.status]}`}</div>
        </article>)}
      </div>
      <form className="chat-composer" onSubmit={onSubmit}><button type="button" aria-label="添加附件"><Plus /></button><textarea aria-label="对话输入" rows={1} value={chatInput} onChange={(event) => onInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="给 WeatherFlow 发消息…" /><button className="send-button" aria-label="发送" disabled={sending || !chatInput.trim()}><PaperPlaneRight weight="fill" /></button></form>
      <footer className="composer-meta"><span>{run ? `当前任务 · ${runStatusText[run.status]}` : "等待新任务"}</span><span>状态策略：静默协作</span></footer>
    </section>
    <aside className="chat-context"><div className="context-heading"><Wrench /><span>当前上下文</span></div><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside>
  </div>;
}

function ContextContent({ pending, artifacts, onDecide, onDownload }: { pending: Approval[]; artifacts: Artifact[]; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <><section><h3>待批准</h3>{pending.length === 0 ? <p>没有需要处理的操作。</p> : pending.map((approval) => <article className="approval-card" key={approval.id}><strong>{approval.tool_id}</strong><pre>{JSON.stringify(approval.preview, null, 2)}</pre><div><button onClick={() => void onDecide(approval, "deny")}>拒绝</button><button className="primary" onClick={() => void onDecide(approval, "approve")}>批准</button></div></article>)}</section><section><h3>产出文件</h3>{artifacts.length === 0 ? <p>暂无文件。</p> : artifacts.map((artifact) => <button className="artifact-link" key={artifact.id} onClick={() => void onDownload(artifact)}>{artifact.name}<small>{artifact.size_bytes} 字节</small></button>)}</section></>;
}

function RunsView({ runs, run, timeline, artifacts, pending, onSelect, onDecide, onDownload }: { runs: Run[]; run: Run | null; timeline: LedgerEvent[]; artifacts: Artifact[]; pending: Approval[]; onSelect: (id: string) => void; onDecide: (approval: Approval, decision: "approve" | "deny") => void; onDownload: (artifact: Artifact) => void }) {
  return <div className="page-view"><header className="page-header"><span>任务</span><h1>执行、批准与产出</h1></header><div className="runs-layout"><div className="run-list">{runs.map((item) => <button className={item.id === run?.id ? "selected" : ""} key={item.id} onClick={() => onSelect(item.id)}><span>{item.user_intent}</span><small>{runStatusText[item.status]}</small></button>)}</div><div className="run-detail">{run ? <><span className={`status-pill ${run.status}`}>{runStatusText[run.status]}</span><h2>{run.user_intent}</h2><p>{run.result_summary ?? "任务仍在处理中。"}</p><h3>执行记录</h3><ol className="timeline">{timeline.slice(-12).reverse().map((event) => <li key={event.id}><i /><div><strong>{event.type.replaceAll(".", " · ")}</strong><time>{new Date(event.recorded_at).toLocaleTimeString("zh-CN")}</time></div></li>)}</ol></> : <p>暂无任务。</p>}</div><aside className="run-context"><ContextContent pending={pending} artifacts={artifacts} onDecide={onDecide} onDownload={onDownload} /></aside></div></div>;
}

function RhythmView({ snapshot, rhythmKind, rhythmText, onKind, onText, onSubmit }: { snapshot: DesktopSnapshot | null; rhythmKind: "checkin" | "correction"; rhythmText: string; onKind: (value: "checkin" | "correction") => void; onText: (value: string) => void; onSubmit: (event: FormEvent) => void }) {
  const scene = snapshot?.rhythm.weather.scene ?? "mixed";
  return <div className="page-view narrow"><header className="page-header"><span>状态天气</span><h1>WeatherFlow 现在如何理解你</h1><p>这会影响提问频率、输出密度和任务拆解方式，不会改变你的目标。</p></header><section className="rhythm-hero" data-scene={scene}><CloudSun size={44} /><div><small>{weatherText[scene]}</small><h2>{snapshot?.rhythm.snapshot.summary ?? "等待你的第一次签到"}</h2></div></section><form className="rhythm-form-large" onSubmit={onSubmit}><select aria-label="状态信号类型" value={rhythmKind} onChange={(event) => onKind(event.target.value as "checkin" | "correction")}><option value="checkin">主动签到</option><option value="correction">修正判断</option></select><textarea aria-label="状态签到" value={rhythmText} onChange={(event) => onText(event.target.value)} placeholder="你现在真实的状态怎么样？" /><button className="primary">保存状态</button></form></div>;
}

function ConnectionsView() {
  const items = [
    { id: "github", name: "GitHub", note: "仓库活动与通知", icon: <GithubLogo weight="fill" /> },
    { id: "gmail", name: "Gmail", note: "未读邮件摘要", icon: <EnvelopeSimple weight="fill" /> },
    { id: "calendar", name: "Google Calendar", note: "近期日程", icon: <CalendarBlank weight="fill" /> },
  ];
  return <div className="page-view"><header className="page-header"><span>连接</span><h1>只连接真正需要的服务</h1><p>授权后可静默自动拉取只读信息；任何外部写入仍然需要批准。</p></header><div className="connection-grid">{items.map((item) => <article key={item.id}><div className={`service-mark ${item.id}`}>{item.icon}</div><h2>{item.name}</h2><p>{item.note}</p><span>需要 OAuth 客户端配置</span><button disabled>等待配置</button></article>)}</div></div>;
}

function SettingsView({ client, system, providers, workspaceId, offline, snapshot, resetPreview, onResetPreview, onOperation }: { client: WeatherFlowClient; system: SystemStatus | null; providers: ModelProviderPreset[]; workspaceId?: string | null; offline: boolean; snapshot: DesktopSnapshot | null; resetPreview: ResetPreview | null; onResetPreview: (value: ResetPreview | null) => void; onOperation: (value: string) => void }) {
  const [selectedProvider, setSelectedProvider] = useState(system?.model?.provider ?? "minimax");
  const preset = providers.find((item) => item.provider === selectedProvider);
  const [model, setModel] = useState(system?.model?.model ?? "MiniMax-M3");
  const [baseUrl, setBaseUrl] = useState(system?.model?.base_url ?? "https://api.minimaxi.com/v1");
  const [apiKey, setApiKey] = useState("");
  const configure = async (event: FormEvent) => { event.preventDefault(); if (!client.configureModel || !workspaceId) return; await client.configureModel({ provider: selectedProvider, model, base_url: baseUrl, api_key: apiKey }, workspaceId); setApiKey(""); onOperation("模型配置已验证并保存到本机钥匙串。"); };
  const chooseProvider = (id: string) => { const next = providers.find((item) => item.provider === id); setSelectedProvider(id); if (next) { setModel(next.default_model); setBaseUrl(next.base_url); } };
  const exportDiagnostics = async () => { const result = await client.exportDiagnostics(workspaceId); onOperation(`诊断文件已保存到本机：${result.path}`); };
  const reviewReset = async () => onResetPreview(await client.previewReset("behavior", workspaceId));
  const reset = async () => { const result = await client.reset("behavior", workspaceId); onResetPreview(null); onOperation(`已删除 ${result.deleted_count} 条行为记录。`); };
  return <div className="page-view settings-view"><header className="page-header"><span>设置</span><h1>模型与本机运行</h1></header><section className="settings-section"><div className="section-title"><h2>语言模型</h2><p>选择国内常用提供商，也可以编辑模型名和 API Endpoint。</p></div><div className="provider-pills">{providers.map((item) => <button className={item.provider === selectedProvider ? "selected" : ""} key={item.provider} onClick={() => chooseProvider(item.provider)}>{item.label}</button>)}</div><form className="model-form" onSubmit={configure}><label>模型名<input value={model} onChange={(event) => setModel(event.target.value)} list="suggested-models" /></label><datalist id="suggested-models">{preset?.suggested_models.map((item) => <option value={item} key={item} />)}</datalist><label>API Endpoint<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label><label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={system?.model?.credential_available ? "已安全保存，留空则不修改" : "仅写入 macOS 钥匙串"} /></label><button className="primary" disabled={!apiKey.trim()}>验证并保存</button></form></section><section className="settings-section"><div className="section-title"><h2>本机与隐私</h2></div><dl><div><dt>项目</dt><dd>{snapshot?.workspace.action_roots[0] ?? "加载中"}</dd></div><div><dt>模型</dt><dd>{system?.model?.configured ? `${system.model.provider} · ${system.model.model}` : "尚未配置"}</dd></div><div><dt>行为感知</dt><dd>{system?.behavior_sensor.enabled ? "已启用元数据" : "仅主动签到"}</dd></div><div><dt>本机桥接</dt><dd>{offline ? "正在恢复" : "已认证"}</dd></div></dl><div className="settings-actions"><button onClick={() => void exportDiagnostics()}>导出本机诊断</button>{!resetPreview ? <button onClick={() => void reviewReset()}>检查行为数据清理</button> : <button className="danger" onClick={() => void reset()}>删除 {resetPreview.count} 条行为记录</button>}</div></section></div>;
}
