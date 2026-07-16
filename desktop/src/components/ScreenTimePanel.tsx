import {
  ArrowsInSimple,
  ArrowsOutSimple,
  Browser,
  ClockCounterClockwise,
  Database,
  Export,
  Eye,
  Pause,
  Play,
  ShieldCheck,
  Timer,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { nativeActivityPermission } from "../activity";
import type { WeatherFlowClient } from "../bridge";
import type {
  ActivityInferenceJob,
  ActivityInterval,
  ActivityPreferences,
  ActivitySummary,
} from "../types";

type LoadState = "loading" | "ready" | "error";

const categoryLabel: Record<string, string> = {
  development: "开发",
  communication: "沟通",
  research: "研究",
  planning: "规划",
  creative: "创作",
  other: "其他",
};

function dayRange(now: Date) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  return { start, end: now };
}

function duration(seconds: number) {
  const rounded = Math.max(0, Math.round(seconds / 60));
  if (rounded < 60) return `${rounded} 分`;
  const hours = Math.floor(rounded / 60);
  const minutes = rounded % 60;
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
}

function time(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function overlapSeconds(event: ActivityInterval, start: Date, end: Date) {
  return Math.max(
    0,
    (Math.min(Date.parse(event.ended_at), end.getTime())
      - Math.max(Date.parse(event.started_at), start.getTime())) / 1000,
  );
}

function hourlyUsage(events: ActivityInterval[], start: Date) {
  const appSwitches = hourlySwitchCounts(events, start, "macos_window", "bundle_id");
  const tabSwitches = hourlySwitchCounts(events, start, "browser_tab", "browser_tab_id");
  return Array.from({ length: 24 }, (_, hour) => {
    const bucketStart = new Date(start.getTime() + hour * 3_600_000);
    const bucketEnd = new Date(bucketStart.getTime() + 3_600_000);
    return {
      hour,
      screen: events
        .filter((event) => event.source === "macos_window" && event.idle_state === "active")
        .reduce((total, event) => total + overlapSeconds(event, bucketStart, bucketEnd), 0),
      browser: events
        .filter((event) => event.source === "browser_tab" && event.idle_state === "active")
        .reduce((total, event) => total + overlapSeconds(event, bucketStart, bucketEnd), 0),
      appSwitches: appSwitches[hour],
      tabSwitches: tabSwitches[hour],
    };
  });
}

function hourlySwitchCounts(
  events: ActivityInterval[],
  start: Date,
  source: ActivityInterval["source"],
  identity: "bundle_id" | "browser_tab_id",
) {
  const buckets = Array.from({ length: 24 }, () => 0);
  const previous = new Map<string, string>();
  [...events]
    .filter((event) => event.source === source && event[identity])
    .sort((left, right) => Date.parse(left.started_at) - Date.parse(right.started_at))
    .forEach((event) => {
      const current = event[identity];
      if (!current) return;
      const prior = previous.get(event.source_instance);
      if (prior && prior !== current) {
        const hour = Math.floor((Date.parse(event.started_at) - start.getTime()) / 3_600_000);
        if (hour >= 0 && hour < 24) buckets[hour] += 1;
      }
      previous.set(event.source_instance, current);
    });
  return buckets;
}

function RawActivityRow({ event }: { event: ActivityInterval }) {
  const identity = event.app_name ?? event.domain ?? "空闲";
  const title = event.window_title ?? event.tab_title ?? "无标题";
  return <li>
    <time>{time(event.started_at)}</time>
    <i data-category={event.idle_state === "idle" ? "idle" : event.category ?? "other"}>{event.source === "browser_tab" ? <Browser /> : <Database />}</i>
    <div>
      <strong>{identity}</strong>
      <p>{title}</p>
      {event.url && <code>{event.url}</code>}
      <details className="raw-event-details">
        <summary>查看完整字段</summary>
        <dl>
          <div><dt>来源</dt><dd>{event.source} · {event.source_instance}</dd></div>
          <div><dt>来源事件</dt><dd>{event.source_event_id}</dd></div>
          <div><dt>时间</dt><dd>{new Date(event.started_at).toLocaleString("zh-CN")} → {new Date(event.ended_at).toLocaleString("zh-CN")}</dd></div>
          <div><dt>应用</dt><dd>{event.app_name ?? "—"} · {event.bundle_id ?? "—"}</dd></div>
          <div><dt>窗口标题</dt><dd>{event.window_title ?? "—"}</dd></div>
          <div><dt>浏览器</dt><dd>{event.browser_name ?? "—"} · 窗口 {event.browser_window_id ?? "—"} · 标签 {event.browser_tab_id ?? "—"}</dd></div>
          <div><dt>标签标题</dt><dd>{event.tab_title ?? "—"}</dd></div>
          <div><dt>完整 URL</dt><dd>{event.url ?? "—"}</dd></div>
          <div><dt>状态</dt><dd>{event.idle_state} · focused {String(event.focused ?? "—")} · audible {String(event.audible ?? "—")} · incognito {String(event.incognito ?? "—")}</dd></div>
        </dl>
      </details>
    </div>
    <small>{duration(event.duration_seconds)}</small>
  </li>;
}

export function ScreenTimePanel({
  client,
  workspaceId,
  now: requestedNow,
  refreshIntervalMs = 15_000,
}: {
  client: WeatherFlowClient;
  workspaceId?: string | null;
  now?: Date;
  refreshIntervalMs?: number;
}) {
  const [state, setState] = useState<LoadState>("loading");
  const [expanded, setExpanded] = useState(false);
  const [preferences, setPreferences] = useState<ActivityPreferences | null>(null);
  const [summary, setSummary] = useState<ActivitySummary | null>(null);
  const [events, setEvents] = useState<ActivityInterval[]>([]);
  const [inference, setInference] = useState<ActivityInferenceJob | null>(null);
  const [inferenceHistory, setInferenceHistory] = useState<ActivityInferenceJob[]>([]);
  const [selected, setSelected] = useState<ActivityInterval | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [macPermission, setMacPermission] = useState<"granted" | "denied" | "unavailable">("unavailable");
  const [range, setRange] = useState(() => dayRange(requestedNow ?? new Date()));

  const load = useCallback(async () => {
    const nextRange = dayRange(requestedNow ?? new Date());
    try {
      const [nextPreferences, nextSummary, nextEvents, history] = await Promise.all([
        client.activityPreferences(),
        client.activitySummary(nextRange.start, nextRange.end),
        client.activityEvents(nextRange.start, nextRange.end),
        client.activityInferenceHistory(20),
      ]);
      setRange(nextRange);
      setPreferences(nextPreferences);
      setSummary(nextSummary);
      setEvents(nextEvents);
      setInference(history[0] ?? null);
      setInferenceHistory(history);
      setMacPermission(await nativeActivityPermission());
      setState("ready");
    } catch {
      setState("error");
    }
  }, [client, requestedNow]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), refreshIntervalMs);
    return () => window.clearInterval(timer);
  }, [load, refreshIntervalMs]);

  const categoryEntries = useMemo(
    () => Object.entries(summary?.category_seconds ?? {}).sort((a, b) => b[1] - a[1]),
    [summary],
  );
  const categoryTotal = categoryEntries.reduce((total, [, seconds]) => total + seconds, 0);
  const hourly = useMemo(() => hourlyUsage(events, range.start), [events, range.start]);
  const streak = summary?.current_streak_seconds ?? 0;
  const idleSeconds = summary?.idle_seconds ?? 0;
  const maxHourlySwitches = Math.max(1, ...hourly.map((bucket) => bucket.appSwitches + bucket.tabSwitches));
  const timelineMarks = (source: ActivityInterval["source"]) => events
    .filter((event) => event.source === source)
    .map((event) => {
      const start = Math.max(0, Date.parse(event.started_at) - range.start.getTime());
      const end = Math.min(86_400_000, Date.parse(event.ended_at) - range.start.getTime());
      const style = {
        left: `${start / 86_400_000 * 100}%`,
        width: `${Math.max(0.18, (end - start) / 86_400_000 * 100)}%`,
      };
      return <button
        type="button"
        key={event.id}
        data-category={event.idle_state === "idle" ? "idle" : event.category ?? "other"}
        style={style}
        aria-label={`${time(event.started_at)} 到 ${time(event.ended_at)} ${event.app_name ?? event.domain ?? "空闲"}`}
        onClick={() => setSelected(event)}
      />;
    });

  const updatePreferences = async (update: Partial<Omit<ActivityPreferences, "version">>) => {
    if (!preferences) return;
    const { version, ...configuration } = preferences;
    try {
      const updated = await client.updateActivityPreferences(
        { ...configuration, ...update },
        version,
      );
      setPreferences(updated);
      setNotice("活动设置已保存");
    } catch {
      setNotice("设置保存失败，请稍后重试");
    }
  };

  const exportToday = async () => {
    const exported = await client.activityExport(range.start, range.end);
    const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `weatherflow-activity-${range.start.toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setNotice(`已导出 ${exported.events.length} 条原始活动`);
  };

  const deleteToday = async () => {
    if (!window.confirm("删除今天的原始活动？此操作无法撤销。")) return;
    const result = await client.deleteActivity(range.start, range.end);
    setNotice(`已删除 ${result.deleted} 条原始活动`);
    await load();
  };

  if (state === "loading") return <section className="screen-time-panel screen-time-state" aria-busy="true"><Timer /><div><strong>正在整理今天的屏幕时间</strong><span>读取本机 Raw Activity Vault…</span></div></section>;
  if (state === "error") return <section className="screen-time-panel screen-time-state error" role="alert"><WarningCircle /><div><strong>屏幕时间暂时不可用</strong><span>WeatherFlow 无法读取活动库，请检查本机桥接。</span></div><button type="button" onClick={() => void load()}>重试</button></section>;
  if (!preferences || !summary) return null;

  const noSource = !preferences.macos_enabled && !preferences.browser_enabled;
  const paused = !preferences.collection_enabled;
  const noData = summary.screen_seconds === 0 && summary.browser_seconds === 0;

  return <section className={`screen-time-panel ${expanded ? "expanded" : "compact"}`}>
    <header className="screen-time-heading">
      <div><span>今日节奏</span><h2>屏幕时间</h2></div>
      <div className="screen-time-heading-actions">
        <span className={`collection-state ${paused || noSource ? "paused" : "active"}`}>{paused ? "已暂停" : noSource ? "等待权限" : "本机记录中"}</span>
        <button type="button" aria-label={expanded ? "收起屏幕时间详情" : "展开屏幕时间详情"} onClick={() => setExpanded((value) => !value)}>{expanded ? <ArrowsInSimple /> : <ArrowsOutSimple />}</button>
      </div>
    </header>

    {paused || noSource ? <div className="screen-time-permission-state"><ShieldCheck /><div><strong>{paused ? "完整活动记录已暂停" : "选择要记录的活动来源"}</strong><p>{paused ? "历史数据仍保留在本机；恢复后继续以 heartbeat 合并记录。" : "macOS 与浏览器分别授权，远程推理另行开启。"}</p></div><button type="button" onClick={() => void updatePreferences({ collection_enabled: true, macos_enabled: true })}><Play />恢复 macOS 记录</button></div> : <>
      {preferences.macos_enabled && macPermission === "denied" && <div className="screen-time-permission-note" role="status"><WarningCircle /><span><strong>窗口标题权限未授予</strong>应用名称与空闲状态仍会记录；在 macOS“隐私与安全性 → 辅助功能”中允许 WeatherFlow 后可补全标题。</span></div>}
      <div className="screen-time-metrics">
        <article className="primary-metric"><span>今日屏幕时间</span><strong>{duration(summary.screen_seconds)}</strong><small>浏览器 {duration(summary.browser_seconds)}</small></article>
        <article><span>当前连续活动</span><strong>{duration(streak)}</strong><small>{streak ? "仍在进行" : "当前没有连续活动"}</small></article>
        <article><span>切换次数</span><strong>{summary.app_switch_count + summary.tab_switch_count}</strong><small>应用 {summary.app_switch_count} · 标签 {summary.tab_switch_count}</small></article>
      </div>
      <div className="activity-allocation" aria-label="今日活动类别分布">
        <div className="allocation-track">{categoryEntries.map(([category, seconds]) => <i key={category} data-category={category} style={{ flexGrow: Math.max(seconds, 1) }} aria-label={`${categoryLabel[category] ?? category} ${duration(seconds)}`} />)}</div>
        <div className="allocation-legend">{categoryEntries.slice(0, 4).map(([category, seconds]) => <span key={category}><i data-category={category} />{categoryLabel[category] ?? category} {categoryTotal ? Math.round(seconds / categoryTotal * 100) : 0}%</span>)}</div>
      </div>
      {noData && <div className="screen-time-data-note"><ClockCounterClockwise />今天还没有足够数据；保持记录几分钟后会出现分布。</div>}
    </>}

    {expanded && <div className="screen-time-expanded">
      <div className="activity-control-row">
        <label><input type="checkbox" checked={preferences.macos_enabled} onChange={(event) => void updatePreferences({ macos_enabled: event.target.checked, collection_enabled: event.target.checked || preferences.browser_enabled })} />macOS 窗口</label>
        <label><input type="checkbox" checked={preferences.browser_enabled} onChange={(event) => void updatePreferences({ browser_enabled: event.target.checked, collection_enabled: event.target.checked || preferences.macos_enabled })} />浏览器标签页</label>
        <label><input type="checkbox" checked={preferences.remote_inference_enabled} onChange={(event) => void updatePreferences({ remote_inference_enabled: event.target.checked, model_workspace_id: event.target.checked ? workspaceId ?? null : preferences.model_workspace_id })} disabled={!workspaceId} />整点远程推理</label>
        <label>保留<select value={preferences.retention_days ?? "unlimited"} onChange={(event) => void updatePreferences({ retention_days: event.target.value === "unlimited" ? null : Number(event.target.value) as 30 | 90 | 365 })}><option value="30">30 天</option><option value="90">90 天</option><option value="365">365 天</option><option value="unlimited">不限期</option></select></label>
        <button type="button" aria-label={paused ? "恢复全部活动记录" : "暂停全部活动记录"} onClick={() => void updatePreferences({ collection_enabled: paused })}>{paused ? <Play /> : <Pause />}{paused ? "恢复" : "暂停"}</button>
      </div>

      <section className="activity-visual-section"><div className="activity-section-title"><div><span>0–24 时</span><h3>全天活动时间线</h3></div><small>点按区间检查原始记录</small></div><div className="timeline-legend"><span><i className="active" />专注 {duration(summary.screen_seconds)}</span><span><i className="browser" />浏览器 {duration(summary.browser_seconds)}</span><span><i className="idle" />空闲 {duration(idleSeconds)}</span></div><div className="timeline-lanes"><div><span>屏幕</span><div className="day-timeline" aria-label="全天屏幕活动时间线">{timelineMarks("macos_window")}</div></div><div><span>网页</span><div className="day-timeline browser-lane" aria-label="全天浏览器活动时间线">{timelineMarks("browser_tab")}</div></div></div><div className="day-axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>{selected && <div className="selected-activity"><Eye /><div><strong>{selected.app_name ?? selected.domain ?? selected.browser_name ?? "空闲"}</strong><span>{time(selected.started_at)}–{time(selected.ended_at)} · {duration(selected.duration_seconds)}</span><p>{selected.window_title ?? selected.tab_title ?? selected.url ?? "没有标题"}</p></div></div>}</section>

      <div className="activity-detail-grid">
        <section className="activity-visual-section"><div className="activity-section-title"><div><span>每小时</span><h3>屏幕与浏览器趋势</h3></div><div className="trend-legend"><span><i className="screen" />屏幕</span><span><i className="browser" />浏览器</span></div></div><ol className="hourly-chart">{hourly.map((bucket) => <li key={bucket.hour} aria-label={`${bucket.hour} 时：屏幕 ${duration(bucket.screen)}，浏览器 ${duration(bucket.browser)}`}><div><i className="screen" style={{ height: `${Math.max(1, bucket.screen / 3600 * 100)}%` }} /><i className="browser" style={{ height: `${Math.max(1, bucket.browser / 3600 * 100)}%` }} /></div>{bucket.hour % 6 === 0 ? <span>{bucket.hour}</span> : <span />}</li>)}</ol><div className="switch-density-heading"><span>切换频率</span><small>应用 + 标签页</small></div><ol className="switch-density-chart">{hourly.map((bucket) => <li key={bucket.hour} aria-label={`${bucket.hour} 时：应用切换 ${bucket.appSwitches} 次，标签切换 ${bucket.tabSwitches} 次`}><i style={{ height: `${Math.max(2, (bucket.appSwitches + bucket.tabSwitches) / maxHourlySwitches * 100)}%` }} /></li>)}</ol></section>
        <section className="activity-visual-section"><div className="activity-section-title"><div><span>时间去向</span><h3>类别占比</h3></div></div><ol className="category-ranking">{categoryEntries.map(([category, seconds]) => <li key={category}><div><span>{categoryLabel[category] ?? category}</span><strong>{duration(seconds)}</strong></div><i><b data-category={category} style={{ width: `${categoryTotal ? seconds / categoryTotal * 100 : 0}%` }} /></i></li>)}</ol></section>
      </div>

      <div className="activity-detail-grid rankings"><section className="activity-visual-section"><div className="activity-section-title"><div><span>前台应用</span><h3>Top 应用</h3></div></div><ol className="activity-ranking-list">{summary.top_apps.map((item, index) => <li key={item.name}><span>{index + 1}</span><strong>{item.name}</strong><small>{duration(item.seconds)}</small></li>)}</ol></section><section className="activity-visual-section"><div className="activity-section-title"><div><span>网页域名</span><h3>Top 网站</h3></div></div><ol className="activity-ranking-list">{summary.top_domains.map((item, index) => <li key={item.name}><span>{index + 1}</span><strong>{item.name}</strong><small>{duration(item.seconds)}</small></li>)}</ol></section></div>

      <section className="activity-visual-section raw-activity-section"><div className="activity-section-title"><div><span>{events.length} 条区间</span><h3>原始活动时间线</h3></div><small>标题和 URL 仅保存在 Raw Activity Vault</small></div><ol className="raw-activity-list">{[...events].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at)).map((event) => <RawActivityRow key={event.id} event={event} />)}</ol></section>

        <section className={`inference-audit ${inference?.status ?? "empty"}`}><div className="activity-section-title"><div><span>状态推理</span><h3>最近一次整点判断</h3></div><span className="inference-status">{inference ? ({ completed: "已完成", executing: "推理中", pending: "等待发送", failed: "失败", needs_review: "需检查" }[inference.status]) : "尚未运行"}</span></div>{inference ? <><div className="inference-summary"><ShieldCheck /><div><strong>{inference.snapshot?.summary ?? "模型尚未返回结构化状态"}</strong><span>{time(inference.window_start)}–{time(inference.window_end)} · {inference.provider ?? "未知提供商"}/{inference.model ?? "未知模型"} · {inference.event_count} 条事件 / {inference.chunk_count} 个原始分片 · {inference.redaction_count} 处脱敏</span></div></div><details><summary>查看发送内容与证据</summary><pre>{inference.request_payload ?? "发送内容尚未生成"}</pre><p>证据：{inference.event_ids.join(" · ") || "无"}</p></details>{inferenceHistory.length > 1 && <ol className="inference-history-list" aria-label="整点推理历史">{inferenceHistory.slice(1, 7).map((job) => <li key={job.id}><time>{time(job.scheduled_for)}</time><strong>{({ completed: "已完成", executing: "推理中", pending: "等待发送", failed: "失败", needs_review: "需检查" }[job.status])}</strong><span>{job.provider ?? "—"}/{job.model ?? "—"}</span><small>{job.event_count} 条</small></li>)}</ol>}</> : <p className="inference-empty">开启“整点远程推理”后，北京时间 06:00–24:00 每小时生成一条可审计快照。</p>}</section>

      <footer className="activity-data-actions"><p><ShieldCheck />不采集截图、键盘、剪贴板、网页正文或音频；凭据写入前脱敏。</p><div><button type="button" onClick={() => void exportToday()}><Export />导出今天</button><button type="button" className="danger" onClick={() => void deleteToday()}><Trash />删除今天</button></div></footer>
    </div>}
    {notice && <p className="screen-time-notice" role="status">{notice}</p>}
  </section>;
}
