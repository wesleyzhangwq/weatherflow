import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow,
  ArrowClockwise,
  CalendarDots,
  ChartBar,
  CheckCircle,
  Clock,
  Database,
  EnvelopeSimple,
  Eye,
  GithubLogo,
  ListChecks,
  PlugsConnected,
  Pulse,
  ShieldWarning,
  Stack,
  TrendUp,
  WarningCircle,
  WifiHigh,
  WifiSlash,
} from "@phosphor-icons/react";
import type { WeatherFlowClient } from "../bridge";
import type {
  ActivityStatistics,
  ActivitySummaryKind,
  ActivitySummaryRecord,
  ActivitySummaryTask,
  ActivityTimelineEntry,
  ActivityTrendPoint,
  ActivityWatchSourceStatus,
  WatchCurrent,
  WatchOAuthFeed,
} from "../types";

const SHANGHAI_TIME_ZONE = "Asia/Shanghai";
const SHANGHAI_UTC_OFFSET_MS = 8 * 60 * 60 * 1_000;
const OAUTH_DAILY_REFRESH_MS = 24 * 60 * 60 * 1_000;
const OAUTH_ITEM_PREVIEW_LENGTH = 180;
const OAUTH_VISIBLE_ITEM_LIMIT = 5;
const SUMMARY_HISTORY_LIMIT = 12;
const SUMMARY_EVIDENCE_PREVIEW_LIMIT = 12;

type LoadState = "loading" | "ready" | "error";
type OptionalLoadState = LoadState | "idle";

const summaryKindText: Record<ActivitySummaryKind, string> = {
  stage_6h: "六小时阶段",
  daily_24h: "过去 24 小时",
  weekly: "周总结",
  biweekly: "双周总结",
  monthly: "月度总结",
};

type WatchOAuthConnector = WatchOAuthFeed["sources"][number]["connector"];

const oauthConnectorOrder: readonly WatchOAuthConnector[] = [
  "github",
  "gmail",
  "google_calendar",
];

const oauthSourcePresentation: Record<WatchOAuthConnector, {
  label: string;
  strategy: string;
  emptyTitle: string;
  emptyDetail: string;
}> = {
  github: {
    label: "GitHub",
    strategy: "每日刷新 · 最近更新与未读通知",
    emptyTitle: "今天没有新的代码动态",
    emptyDetail: "这里会显示最近的仓库活动、通知和协作更新。",
  },
  gmail: {
    label: "Gmail",
    strategy: "每日刷新 · 未读邮件与最近消息",
    emptyTitle: "当前没有未读或新增邮件",
    emptyDetail: "连接健康；本次每日快照没有需要展示的新邮件。",
  },
  google_calendar: {
    label: "Google Calendar",
    strategy: "每日刷新 · 近期已结束与未来日程",
    emptyTitle: "当前时间窗口没有日程",
    emptyDetail: "这里会同时呈现近期已结束和即将开始的日程。",
  },
};

const secondarySummaryKinds: readonly ActivitySummaryKind[] = [
  "stage_6h",
  "weekly",
  "biweekly",
  "monthly",
];

const taskStatusText: Record<ActivitySummaryTask["status"], string> = {
  pending: "等待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  needs_retry: "等待重试",
};

const oauthHealthText: Record<WatchOAuthFeed["sources"][number]["health"], string> = {
  healthy: "同步正常",
  degraded: "同步异常",
  requires_reconnect: "需要重新授权",
  disabled: "自动抓取已关闭",
  unavailable: "尚不可用",
  stale: "快照已过期",
};

const oauthNormalizationHealthText: Record<
  WatchOAuthFeed["sources"][number]["normalization_health"],
  string
> = {
  unknown: "等待解析验证",
  healthy: "解析完整",
  partial: "部分记录未能解析",
  failed: "解析失败",
};

const summaryFallbackText: Record<string, string> = {
  activity_coverage_none: "ActivityWatch 覆盖为空，已使用本地可追溯总结",
  activity_model_route_unavailable: "所选模型路由不可用，已使用本地可追溯总结",
  activity_model_authentication_failed: "模型凭证校验失败，已使用本地可追溯总结",
  activity_model_temporarily_unavailable: "模型暂时不可用，已使用本地可追溯总结",
  activity_model_invalid_response: "模型响应无效，已使用本地可追溯总结",
  activity_model_connection_failed: "模型连接失败，已使用本地可追溯总结",
  activity_model_output_rejected: "模型输出未通过安全校验，已使用本地可追溯总结",
};

const summaryConnectorLabel: Record<
  ActivitySummaryRecord["connector_coverage"][number]["connector"],
  string
> = {
  github: "GitHub",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
};

function summaryConnectorCoverageText(summary: ActivitySummaryRecord): string {
  if (!summary.connector_coverage.length) return "旧版总结未记录来源覆盖";
  return summary.connector_coverage.map((source) => {
    const snapshot = source.snapshot_fetched_at
      ? ` · 快照 ${formatDateTime(source.snapshot_fetched_at)}`
      : " · 无快照";
    return `${summaryConnectorLabel[source.connector]} ${oauthHealthText[source.health]} ${source.window_item_count} 条${snapshot} · 水位 ${source.snapshot_watermark.slice(0, 12)}`;
  }).join("；");
}

function oauthSourceStatusText(source: WatchOAuthFeed["sources"][number]): string {
  if (source.last_error_code === "broker_auth") return "Composio 连接密钥失效";
  if (source.last_error_code === "broker_permission") return "Composio 密钥权限不足";
  if (source.last_error_code === "project_changed") return "项目已更换，需要重新授权";
  if (source.last_error_code === "auth_config_required") return "OAuth 应用配置缺失";
  return oauthHealthText[source.health];
}

function formatDuration(seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 1) return "不足 1 分";
  if (minutes < 60) return `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "时间未知";
  return parsed.toLocaleString("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function compactReference(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 24 ? `${value.slice(0, 20)}…` : value;
}

function summarySortValue(summary: ActivitySummaryRecord): [number, number, string] {
  return [
    Date.parse(summary.window_end) || 0,
    Date.parse(summary.completed_at) || 0,
    summary.id,
  ];
}

function compareSummariesNewestFirst(
  left: ActivitySummaryRecord,
  right: ActivitySummaryRecord,
): number {
  const [leftWindow, leftCompleted, leftId] = summarySortValue(left);
  const [rightWindow, rightCompleted, rightId] = summarySortValue(right);
  if (leftWindow !== rightWindow) return rightWindow - leftWindow;
  if (leftCompleted !== rightCompleted) return rightCompleted - leftCompleted;
  return rightId.localeCompare(leftId);
}

function isNewerSummary(
  candidate: ActivitySummaryRecord,
  existing: ActivitySummaryRecord,
): boolean {
  const candidateWindow = Date.parse(candidate.window_end) || 0;
  const existingWindow = Date.parse(existing.window_end) || 0;
  if (candidateWindow !== existingWindow) return candidateWindow > existingWindow;
  const candidateCompleted = Date.parse(candidate.completed_at) || 0;
  const existingCompleted = Date.parse(existing.completed_at) || 0;
  return candidateCompleted > existingCompleted;
}

function startOfShanghaiDay(value: Date): Date {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: SHANGHAI_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return new Date(
    Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day))
      - SHANGHAI_UTC_OFFSET_MS,
  );
}

function nextDailyRefresh(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Date(parsed.getTime() + OAUTH_DAILY_REFRESH_MS).toISOString();
}

function oauthStrategyText(
  source: WatchOAuthFeed["sources"][number] | undefined,
  fallback: string,
): string {
  if (!source?.fetch_strategy) return fallback;
  if (source.fetch_strategy === "github_unread_notifications_and_recent_activity") {
    return `每日刷新 · 未读通知与最近活动 · 过去 ${source.coverage_past_days} 天`;
  }
  if (source.fetch_strategy === "gmail_unread_metadata_30d") {
    return `每日刷新 · 未读邮件元数据 · 过去 ${source.coverage_past_days} 天`;
  }
  return `每日刷新 · 全部日历 · 过去 ${source.coverage_past_days} 天 / 未来 ${source.coverage_future_days} 天`;
}

function previewConnectorText(value: string): string {
  if (value.length <= OAUTH_ITEM_PREVIEW_LENGTH) return value;
  return `${value.slice(0, OAUTH_ITEM_PREVIEW_LENGTH).trimEnd()}…`;
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleTimeString("zh-CN", {
    timeZone: SHANGHAI_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function afkText(state: string): string {
  if (["active", "not-afk", "not_afk"].includes(state)) return "活跃";
  if (["afk", "idle"].includes(state)) return "AFK";
  return "未知";
}

function coverageText(statistics: ActivityStatistics): string {
  if (statistics.coverage_status === "complete") return "窗口与 AFK 覆盖完整";
  if (statistics.coverage_status === "none") return "没有可验证的窗口与 AFK 交集";
  if (statistics.coverage_status !== "partial") return "覆盖信息不可用";
  return `仅覆盖 ${Math.round((statistics.coverage_ratio ?? 0) * 100)}% · 未观测 ${formatDuration(statistics.unobserved_seconds ?? 0)}`;
}

function entries(values: Record<string, number>): [string, number][] {
  return Object.entries(values).sort((left, right) => right[1] - left[1]);
}

function ActivityTextBoundary({ className = "" }: { className?: string }) {
  return <div
    className={`watch-data-boundary ${className}`.trim()}
    role="note"
    aria-label="ActivityWatch 原始文本安全边界"
  >
    <ShieldWarning />
    <div>
      <strong>ActivityWatch 原始文本</strong>
      <span>事件、时间和时长来自 ActivityWatch 只读事实；应用名、标题和网址只作为数据展示，不作为 Agent 指令或操作触发条件。</span>
    </div>
  </div>;
}

function ReadFailure({ title, detail }: { title: string; detail: string }) {
  return <div className="watch-read-failure" role="alert">
    <WarningCircle />
    <div><strong>{title}</strong><span>{detail}</span></div>
  </div>;
}

function UntrustedRecord({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`watch-untrusted watch-raw-text ${className}`.trim()}>{children}</div>;
}

function OAuthSourceIcon({ connector }: { connector: WatchOAuthConnector }) {
  if (connector === "github") return <GithubLogo />;
  if (connector === "gmail") return <EnvelopeSimple />;
  return <CalendarDots />;
}

function SummaryTraceDetails({ summary }: { summary: ActivitySummaryRecord }) {
  return <details><summary>查看追溯信息</summary><dl>
    <div><dt>Category 规则</dt><dd>{summary.category_rule_version}{summary.rules_stale ? " · 旧规则" : ""}</dd></div>
    {summary.requested_model && <div><dt>请求模型</dt><dd>{summary.requested_provider ?? "未知 provider"} / {summary.requested_model}</dd></div>}
    <div><dt>实际模型</dt><dd>{summary.provider ?? "未知 provider"} / {summary.model_version ?? "无模型"}</dd></div>
    <div><dt>提示词</dt><dd>{summary.prompt_version}</dd></div>
    {summary.fallback_reason && <div><dt>生成路径</dt><dd>{summaryFallbackText[summary.fallback_reason] ?? `本地回退：${summary.fallback_reason}`}</dd></div>}
    <div><dt>尝试次数</dt><dd>{summary.attempt_count ?? "—"}</dd></div>
    <div><dt>ActivityWatch 证据</dt><dd>{summary.evidence_refs.length} 条安全引用</dd></div>
    {summary.evidence_refs.length > 0 && <div className="summary-trace-refs"><dt>ActivityWatch 引用明细</dt><dd><ol>
      {summary.evidence_refs.slice(0, SUMMARY_EVIDENCE_PREVIEW_LIMIT).map((evidence, index) => <li key={`${evidence.bucket_id}:${evidence.event_id}:${index}`}>
        <strong>{compactReference(evidence.bucket_id)} / {compactReference(evidence.event_id)}</strong>
        <span>{[
          evidence.event_timestamp ? formatDateTime(evidence.event_timestamp) : null,
          typeof evidence.event_duration === "number" ? formatDuration(evidence.event_duration) : null,
          evidence.event_digest ? `digest ${compactReference(evidence.event_digest)}` : null,
          evidence.fields_used?.length ? `字段 ${evidence.fields_used.join("、")}` : null,
        ].filter(Boolean).join(" · ") || "仅保存可复核来源标识"}</span>
      </li>)}
    </ol>{summary.evidence_refs.length > SUMMARY_EVIDENCE_PREVIEW_LIMIT && <small>另有 {summary.evidence_refs.length - SUMMARY_EVIDENCE_PREVIEW_LIMIT} 条引用未在紧凑视图展开。</small>}</dd></div>}
    <div><dt>OAuth 证据</dt><dd>{summary.connector_evidence_refs?.length ?? 0} 条安全引用</dd></div>
    {summary.connector_evidence_refs?.length > 0 && <div className="summary-trace-refs"><dt>OAuth 引用明细</dt><dd><ol>
      {summary.connector_evidence_refs.slice(0, SUMMARY_EVIDENCE_PREVIEW_LIMIT).map((evidence, index) => <li key={`${evidence.connector}:${evidence.source_id_digest}:${index}`}>
        <strong>{summaryConnectorLabel[evidence.connector]} · {compactReference(evidence.source_id_digest)} · {compactReference(evidence.item_digest)}</strong>
        <span>发生 {formatDateTime(evidence.occurred_at)}{evidence.ends_at ? ` – ${formatDateTime(evidence.ends_at)}` : ""} · 快照 {formatDateTime(evidence.snapshot_fetched_at)}</span>
      </li>)}
    </ol>{summary.connector_evidence_refs.length > SUMMARY_EVIDENCE_PREVIEW_LIMIT && <small>另有 {summary.connector_evidence_refs.length - SUMMARY_EVIDENCE_PREVIEW_LIMIT} 条引用未在紧凑视图展开。</small>}</dd></div>}
    <div><dt>OAuth 覆盖</dt><dd>{summaryConnectorCoverageText(summary)}</dd></div>
    <div><dt>来源水位</dt><dd>{summary.source_watermark ?? "—"}</dd></div>
  </dl></details>;
}

function OAuthSourceSection({
  connector,
  source,
  items,
  expandedItems,
  onToggleItem,
}: {
  connector: WatchOAuthConnector;
  source: WatchOAuthFeed["sources"][number] | undefined;
  items: WatchOAuthFeed["items"];
  expandedItems: ReadonlySet<string>;
  onToggleItem: (itemKey: string) => void;
}) {
  const presentation = oauthSourcePresentation[connector];
  const lastRefresh = source?.last_sync_at ?? source?.snapshot_fetched_at ?? null;
  const nextRefresh = source?.next_sync_at ?? nextDailyRefresh(lastRefresh);
  const visibleItems = items.slice(0, OAUTH_VISIBLE_ITEM_LIMIT);
  const health = source?.health ?? "unavailable";
  const healthText = source ? oauthSourceStatusText(source) : "尚不可用";
  const canConfirmEmpty = health === "healthy"
    && source?.normalization_health === "healthy"
    && source.item_count === 0
    && items.length === 0;

  return <section
    className="oauth-source-section"
    aria-label={`${presentation.label} 自动抓取`}
    data-health={health}
  >
    <header className="oauth-source-header">
      <div className="oauth-source-title"><OAuthSourceIcon connector={connector} /><div><h3>{presentation.label}</h3><p>{oauthStrategyText(source, presentation.strategy)}</p></div></div>
      <span className="oauth-source-health">{healthText}</span>
    </header>
    <dl className="oauth-source-refresh">
      <div><dt>上次刷新</dt><dd>{lastRefresh ? <time dateTime={lastRefresh}>{formatDateTime(lastRefresh)}</time> : "尚无成功快照"}</dd></div>
      <div><dt>下次预计</dt><dd>{nextRefresh ? <time dateTime={nextRefresh}>{formatDateTime(nextRefresh)}</time> : "等待首次成功刷新"}</dd></div>
      <div><dt>当前条目</dt><dd>{source?.item_count ?? items.length} 条</dd></div>
    </dl>
    {source?.normalization_health && <div
      className="oauth-normalization"
      data-health={source.normalization_health}
      role={source.normalization_health === "failed" ? "alert" : "status"}
    >
      <span>原始 {source.raw_item_count ?? "—"} · 已解析 {source.normalized_item_count ?? "—"}</span>
      <strong>{oauthNormalizationHealthText[source.normalization_health]}</strong>
    </div>}
    {source?.last_error_code && <div className="oauth-source-error" role="status"><WarningCircle /><span>最近刷新失败</span><code>{source.last_error_code}</code></div>}
    {visibleItems.length
      ? <ol className="oauth-source-items">{visibleItems.map((item, index) => {
        const itemKey = `${connector}:${item.source_id}`;
        const expanded = expandedItems.has(itemKey);
        const preview = previewConnectorText(item.summary);
        const expandable = preview !== item.summary || Boolean(item.url);
        const contentId = `oauth-${connector}-item-${index + 1}`;
        return <li key={itemKey}>
          <header><time dateTime={item.occurred_at}>{formatDateTime(item.occurred_at)}</time></header>
          <UntrustedRecord className="oauth-source-record">
            <strong>{item.title}</strong>
            <div id={contentId} className="oauth-source-record-content">
              {item.summary && <p>{expanded ? item.summary : preview}</p>}
              {expanded && item.url && <code>{item.url}</code>}
            </div>
          </UntrustedRecord>
          {expandable && <button
            type="button"
            className="oauth-item-expand"
            aria-expanded={expanded}
            aria-controls={contentId}
            aria-label={`${expanded ? "收起" : "展开"} ${presentation.label} 第 ${index + 1} 条原始内容`}
            onClick={() => onToggleItem(itemKey)}
          >{expanded ? "收起原始内容" : "展开原始内容"}</button>}
        </li>;
      })}</ol>
      : <div className={`oauth-source-empty ${canConfirmEmpty ? "" : "unconfirmed"}`.trim()}>
        <strong>{canConfirmEmpty ? presentation.emptyTitle : "暂时无法确认是否有新内容"}</strong>
        <p>{canConfirmEmpty ? presentation.emptyDetail : "保留最近状态；来源恢复或完成首次刷新后再确认内容覆盖。"}</p>
      </div>}
    {items.length > visibleItems.length && <p className="oauth-source-overflow">另有 {items.length - visibleItems.length} 条内容未在此紧凑视图展开。</p>}
  </section>;
}

interface WatchViewProps {
  client: WeatherFlowClient;
  workspaceId?: string | null;
  now?: Date;
  refreshIntervalMs?: number;
  ledgerRefreshIntervalMs?: number;
  historyRefreshIntervalMs?: number;
  trendRefreshIntervalMs?: number;
  feedRefreshIntervalMs?: number;
}

export function WatchView({
  client,
  workspaceId,
  now,
  refreshIntervalMs = 30_000,
  ledgerRefreshIntervalMs = 60_000,
  historyRefreshIntervalMs = 300_000,
  trendRefreshIntervalMs = 900_000,
  feedRefreshIntervalMs = 60_000,
}: WatchViewProps) {
  const fixedNow = now?.getTime();
  const generations = useRef({ live: 0, history: 0, ledger: 0, trends: 0, feed: 0 });
  const feedWorkspace = useRef<string | null>(workspaceId ?? null);
  const previousSourceReachability = useRef<boolean | null>(null);
  const [source, setSource] = useState<ActivityWatchSourceStatus | null>(null);
  const [current, setCurrent] = useState<WatchCurrent | null>(null);
  const [currentLoadState, setCurrentLoadState] = useState<LoadState>("loading");
  const [statistics, setStatistics] = useState<ActivityStatistics | null>(null);
  const [timeline, setTimeline] = useState<ActivityTimelineEntry[]>([]);
  const [historyLoadState, setHistoryLoadState] = useState<LoadState>("loading");
  const [summaries, setSummaries] = useState<ActivitySummaryRecord[]>([]);
  const [summaryLoadState, setSummaryLoadState] = useState<LoadState>("loading");
  const [tasks, setTasks] = useState<ActivitySummaryTask[]>([]);
  const [taskLoadState, setTaskLoadState] = useState<LoadState>("loading");
  const [weeklyTrends, setWeeklyTrends] = useState<ActivityTrendPoint[]>([]);
  const [monthlyTrends, setMonthlyTrends] = useState<ActivityTrendPoint[]>([]);
  const [trendLoadState, setTrendLoadState] = useState<LoadState>("loading");
  const [oauthFeed, setOAuthFeed] = useState<WatchOAuthFeed | null>(null);
  const [oauthFeedLoadState, setOAuthFeedLoadState] = useState<OptionalLoadState>(
    workspaceId ? "loading" : "idle",
  );
  const [expandedOAuthItems, setExpandedOAuthItems] = useState<Set<string>>(() => new Set());
  const [regeneratingTaskId, setRegeneratingTaskId] = useState<string | null>(null);
  const [regenerationError, setRegenerationError] = useState<string | null>(null);

  const refreshLive = useCallback(async () => {
    const currentGeneration = generations.current.live + 1;
    generations.current.live = currentGeneration;
    const end = new Date(fixedNow ?? Date.now());
    const results = await Promise.allSettled([
      client.watchSourceStatus(),
      client.watchCurrent(),
    ] as const);
    if (generations.current.live !== currentGeneration) return;
    const [sourceResult, currentResult] = results;
    const nextSource = sourceResult.status === "fulfilled"
      ? sourceResult.value
      : {
        reachable: false,
        server_version: null,
        data_start: null,
        data_end: null,
        checked_at: end.toISOString(),
        last_reconciled_at: null,
        error_code: "watch_source_status_unavailable",
      };
    setSource(nextSource);
    if (nextSource.reachable && currentResult.status === "fulfilled") {
      setCurrent(currentResult.value);
      setCurrentLoadState("ready");
    } else {
      setCurrent(null);
      setCurrentLoadState("error");
    }
    if (!nextSource.reachable) {
      setStatistics(null);
      setTimeline([]);
      setHistoryLoadState("error");
    }
  }, [client, fixedNow]);

  const refreshHistory = useCallback(async () => {
    const currentGeneration = generations.current.history + 1;
    generations.current.history = currentGeneration;
    const end = new Date(fixedNow ?? Date.now());
    const start = startOfShanghaiDay(end);
    const results = await Promise.allSettled([
      client.watchDashboard(start, end, 500),
    ] as const);
    if (generations.current.history !== currentGeneration) return;
    const [dashboardResult] = results;
    if (dashboardResult.status === "fulfilled") {
      setStatistics(dashboardResult.value.statistics);
      setTimeline(dashboardResult.value.timeline);
      setHistoryLoadState("ready");
    } else {
      setHistoryLoadState("error");
    }
  }, [client, fixedNow]);

  const refreshLedger = useCallback(async () => {
    const currentGeneration = generations.current.ledger + 1;
    generations.current.ledger = currentGeneration;
    const results = await Promise.allSettled([
      client.watchSummaries(20),
      Promise.all([
        client.watchTasks(30, "pending"),
        client.watchTasks(30, "running"),
        client.watchTasks(30, "needs_retry"),
        client.watchTasks(30, "failed"),
      ]).then((groups) => groups.flat()),
    ] as const);
    if (generations.current.ledger !== currentGeneration) return;
    const [summariesResult, tasksResult] = results;
    if (summariesResult.status === "fulfilled") {
      setSummaries(summariesResult.value);
      setSummaryLoadState("ready");
    } else {
      setSummaryLoadState("error");
    }
    if (tasksResult.status === "fulfilled") {
      setTasks(tasksResult.value);
      setTaskLoadState("ready");
    } else {
      setTaskLoadState("error");
    }
  }, [client]);

  const refreshTrends = useCallback(async () => {
    const currentGeneration = generations.current.trends + 1;
    generations.current.trends = currentGeneration;
    const end = new Date(fixedNow ?? Date.now());
    const trendStart = new Date(end.getTime() - (12 * 7 * 24 * 60 * 60 * 1_000));
    const monthlyTrendStart = new Date(end.getTime() - (365 * 24 * 60 * 60 * 1_000));
    const results = await Promise.allSettled([
      client.watchTrends(trendStart, end, "week"),
      client.watchTrends(monthlyTrendStart, end, "month"),
    ] as const);
    if (generations.current.trends !== currentGeneration) return;
    const [weeklyTrendsResult, monthlyTrendsResult] = results;
    if (weeklyTrendsResult.status === "fulfilled" && monthlyTrendsResult.status === "fulfilled") {
      setWeeklyTrends(weeklyTrendsResult.value);
      setMonthlyTrends(monthlyTrendsResult.value);
      setTrendLoadState("ready");
    } else {
      if (weeklyTrendsResult.status === "fulfilled") setWeeklyTrends(weeklyTrendsResult.value);
      if (monthlyTrendsResult.status === "fulfilled") setMonthlyTrends(monthlyTrendsResult.value);
      setTrendLoadState("error");
    }
  }, [client, fixedNow]);

  const refreshOAuthFeed = useCallback(async () => {
    const currentGeneration = generations.current.feed + 1;
    generations.current.feed = currentGeneration;
    if (!workspaceId) {
      feedWorkspace.current = null;
      setOAuthFeed(null);
      setOAuthFeedLoadState("idle");
      return;
    }
    if (feedWorkspace.current !== workspaceId) {
      feedWorkspace.current = workspaceId;
      setOAuthFeed(null);
      setOAuthFeedLoadState("loading");
    }
    try {
      const next = await client.watchOAuthFeed(workspaceId, 30);
      if (generations.current.feed === currentGeneration) {
        setOAuthFeed(next);
        setOAuthFeedLoadState("ready");
      }
    } catch {
      if (generations.current.feed === currentGeneration) setOAuthFeedLoadState("error");
    }
  }, [client, workspaceId]);

  useEffect(() => {
    const activeGenerations = generations.current;
    void Promise.all([
      refreshLive(),
      refreshHistory(),
      refreshLedger(),
      refreshTrends(),
      refreshOAuthFeed(),
    ]);
    const liveTimer = window.setInterval(() => { void refreshLive(); }, refreshIntervalMs);
    const ledgerTimer = window.setInterval(
      () => { void refreshLedger(); },
      ledgerRefreshIntervalMs,
    );
    const historyTimer = window.setInterval(
      () => { void refreshHistory(); },
      historyRefreshIntervalMs,
    );
    const trendTimer = window.setInterval(
      () => { void refreshTrends(); },
      trendRefreshIntervalMs,
    );
    const feedTimer = window.setInterval(
      () => { void refreshOAuthFeed(); },
      feedRefreshIntervalMs,
    );
    return () => {
      activeGenerations.live += 1;
      activeGenerations.history += 1;
      activeGenerations.ledger += 1;
      activeGenerations.trends += 1;
      activeGenerations.feed += 1;
      window.clearInterval(liveTimer);
      window.clearInterval(ledgerTimer);
      window.clearInterval(historyTimer);
      window.clearInterval(trendTimer);
      window.clearInterval(feedTimer);
    };
  }, [
    historyRefreshIntervalMs,
    feedRefreshIntervalMs,
    ledgerRefreshIntervalMs,
    refreshHistory,
    refreshIntervalMs,
    refreshLedger,
    refreshLive,
    refreshOAuthFeed,
    refreshTrends,
    trendRefreshIntervalMs,
  ]);

  useEffect(() => {
    const nextReachability = source?.reachable ?? null;
    const previousReachability = previousSourceReachability.current;
    previousSourceReachability.current = nextReachability;
    if (previousReachability === false && nextReachability === true) {
      void refreshHistory();
    }
  }, [refreshHistory, source?.reachable]);

  const regenerateTask = async (taskId: string) => {
    if (regeneratingTaskId) return;
    setRegeneratingTaskId(taskId);
    setRegenerationError(null);
    try {
      await client.watchRegenerateTask(taskId);
      await refreshLedger();
    } catch {
      setRegenerationError("无法提交重生成任务，请稍后重试。");
    } finally {
      setRegeneratingTaskId(null);
    }
  };

  const latestByKind = useMemo(() => {
    const result = new Map<ActivitySummaryKind, ActivitySummaryRecord>();
    for (const summary of summaries) {
      const existing = result.get(summary.kind);
      if (!existing || isNewerSummary(summary, existing)) {
        result.set(summary.kind, summary);
      }
    }
    return result;
  }, [summaries]);
  const latestByTask = useMemo(() => {
    const result = new Map<string, ActivitySummaryRecord>();
    for (const summary of summaries) {
      const existing = result.get(summary.task_id);
      if (!existing || isNewerSummary(summary, existing)) result.set(summary.task_id, summary);
    }
    return result;
  }, [summaries]);
  const historicalSummaries = useMemo(() => {
    const featuredIds = new Set([...latestByKind.values()].map((summary) => summary.id));
    return summaries
      .filter((summary) => !featuredIds.has(summary.id))
      .sort(compareSummariesNewestFirst)
      .slice(0, SUMMARY_HISTORY_LIMIT);
  }, [latestByKind, summaries]);
  const latestFirstTimeline = useMemo(
    () => [...timeline].sort((left, right) => {
      const byEnd = Date.parse(right.ended_at) - Date.parse(left.ended_at);
      if (byEnd !== 0) return byEnd;
      const byStart = Date.parse(right.started_at) - Date.parse(left.started_at);
      if (byStart !== 0) return byStart;
      return right.id.localeCompare(left.id);
    }),
    [timeline],
  );
  const dailySummary = latestByKind.get("daily_24h");
  const actionableTasks = tasks.filter((task) => task.status !== "completed");
  const failedTaskCount = tasks.filter((task) => task.status === "failed").length;
  const toggleOAuthItem = (itemKey: string) => {
    setExpandedOAuthItems((currentItems) => {
      const nextItems = new Set(currentItems);
      if (nextItems.has(itemKey)) nextItems.delete(itemKey);
      else nextItems.add(itemKey);
      return nextItems;
    });
  };

  return <div className="page-view watch-view">
    <header className="page-header watch-header">
      <div><span>WATCH</span><h1>活动与总结</h1><p>实时事实直接读取 ActivityWatch；总结、趋势与任务账本来自 WeatherFlow 派生数据库。</p></div>
      {source === null
        ? <div className="watch-source-state" role="status" aria-label="正在检查 ActivityWatch"><Database /><div><strong>正在检查 ActivityWatch</strong><small>建立本机只读连接</small></div></div>
        : source.reachable
          ? <div className="watch-source-state online" role="status" aria-label="ActivityWatch 在线"><WifiHigh /><div><strong>ActivityWatch 在线</strong><small>只读连接 · v{source.server_version?.replace(/^v\s*/i, "") ?? "未知"}</small></div></div>
          : <div className="watch-source-state offline" role="status" aria-label="ActivityWatch 离线"><WifiSlash /><div><strong>ActivityWatch 离线</strong><small>历史总结仍可查看</small></div></div>}
    </header>

    <div className="watch-content">
      <details className="watch-source-strip">
        <summary><Database /><div><strong>ActivityWatch 只读来源</strong><span>原始事实仍由 ActivityWatch 独立保存；展开可查看范围与补偿状态。</span></div><b>来源详情</b></summary>
        <dl>
          <div><dt>最近检查</dt><dd>{formatDateTime(source?.checked_at ?? null)}</dd></div>
          <div><dt>最近补偿</dt><dd>{formatDateTime(source?.last_reconciled_at ?? null)}</dd></div>
          <div><dt>可用范围</dt><dd>{source?.data_start ? `${formatDateTime(source.data_start)} – ${formatDateTime(source.data_end)}` : "等待数据"}</dd></div>
          <div><dt>来源状态</dt><dd>{source ? (source.reachable ? "只读可用" : source.error_code ?? "不可用") : "检查中"}</dd></div>
        </dl>
        <p>WeatherFlow 不启动、停止、配置或写入 ActivityWatch。</p>
      </details>

      <div className="watch-overview-grid" role="region" aria-label="当前活动概览">
        <section className="watch-card observed-card">
          <div className="watch-card-heading"><div><span>ACTIVITYWATCH FACT</span><h2>实时观测</h2></div><Eye /></div>
          {source === null
            ? <div className="watch-empty"><Clock /><strong>正在读取实时事实</strong><p>WeatherFlow 正在建立 ActivityWatch 只读连接。</p></div>
            : !source.reachable
              ? <div className="watch-empty live-offline"><WifiSlash /><strong>实时事实暂不可用</strong><p>不会用缓存伪装成当前状态；ActivityWatch 恢复后会自动重连。</p></div>
              : currentLoadState === "error"
                ? <div className="watch-empty live-offline"><WarningCircle /><strong>实时事实读取失败</strong><p>ActivityWatch 服务在线，但本次当前活动查询没有成功；不会把失败当作“没有活动”。</p></div>
              : current?.observed
              ? <div className="observed-fact">
                <div className="observed-app"><AppWindow /><div><strong>{current.observed.app_name ?? "未知应用"}</strong><small>自 {formatTime(current.observed.started_at)} 起</small></div></div>
                <dl className="watch-live-metrics">
                  <div><dt>持续时间</dt><dd>{formatDuration(current.observed.duration_seconds)}</dd></div>
                  <div><dt>AFK 状态</dt><dd data-afk={current.afk_state ?? current.observed.afk_state}>{afkText(current.afk_state ?? current.observed.afk_state)}</dd></div>
                  <div><dt>观测时间</dt><dd>{formatTime(current.observed_at ?? current.observed.observed_at)}</dd></div>
                </dl>
                {(current.observed.window_title || current.observed.url) && <div className="watch-raw-text-group">
                  <ActivityTextBoundary />
                  <UntrustedRecord>
                    {current.observed.window_title && <p>{current.observed.window_title}</p>}
                    {current.observed.url && <code>{current.observed.url}</code>}
                  </UntrustedRecord>
                </div>}
              </div>
              : current
                ? <div className="watch-empty"><Clock /><strong>没有当前前台窗口</strong><p>AFK 状态：{afkText(current.afk_state)} · 观测于 {formatTime(current.observed_at)}</p></div>
                : <div className="watch-empty"><Clock /><strong>还没有当前活动</strong><p>ActivityWatch 在线，但此刻没有可用的前台或 AFK 事实。</p></div>}
        </section>

        <section className="watch-card today-overview-card">
          <div className="watch-card-heading"><div><span>ASIA/SHANGHAI · TODAY</span><h2>今日概览</h2></div><Pulse /></div>
          {statistics
            ? <>
              {historyLoadState === "error" && <ReadFailure title="今日统计刷新失败" detail="当前显示上次成功读取的结果，不会把它冒充为刚刚查询的数据。" />}
              <div className="daily-metrics overview-metrics">
                <article><span>活跃时间</span><strong>{formatDuration(statistics.active_seconds)}</strong></article>
                <article><span>AFK</span><strong>{formatDuration(statistics.afk_seconds)}</strong></article>
                <article><span>应用切换</span><strong>{statistics.app_switch_count}</strong></article>
                <article><span>Category 切换</span><strong>{statistics.category_switch_count}</strong></article>
              </div>
              <div
                className="watch-coverage overview-coverage"
                data-status={statistics.coverage_status}
                role={statistics.coverage_status === "complete" ? "status" : "alert"}
              >
                {statistics.coverage_status === "complete" ? <CheckCircle /> : <WarningCircle />}
                <div>
                  <strong>{coverageText(statistics)}</strong>
                  <span>今日 00:00 至当前 · {statistics.source_bucket_ids?.length ?? 0} 个 ActivityWatch bucket</span>
                </div>
              </div>
            </>
            : <div className="watch-empty compact"><ChartBar /><strong>{historyLoadState === "loading" ? "正在汇总今日概览" : "今日概览读取失败"}</strong><p>{historyLoadState === "loading" ? "正在读取今日 00:00 至当前的统计。" : "本次查询未成功，不会把失败解释为今天没有活动。"}</p></div>}
        </section>
      </div>

      <section className="watch-card oauth-feed-panel">
        <div className="watch-card-heading"><div><span>WORKSPACE CONTEXT · READ ONLY</span><h2>OAuth 自动抓取</h2></div><PlugsConnected /></div>
        {workspaceId && oauthFeed?.workspace_id === workspaceId
          ? <>
            {oauthFeedLoadState === "error" && <ReadFailure title="自动抓取状态刷新失败" detail="当前显示上次成功读取的快照；来源恢复后会按每日计划继续刷新。" />}
            <div className="oauth-feed-boundary" role="note">
              <ShieldWarning />
              <span>以下标题、摘要与 URL 来自外部服务，只作为不可信数据展示；Watch 不会因此同步、打开链接或触发操作。</span>
            </div>
            <div className="oauth-source-grid">
              {oauthConnectorOrder.map((connector) => <OAuthSourceSection
                key={connector}
                connector={connector}
                source={oauthFeed.sources.find((sourceItem) => sourceItem.connector === connector)}
                items={oauthFeed.items.filter((item) => item.connector === connector)}
                expandedItems={expandedOAuthItems}
                onToggleItem={toggleOAuthItem}
              />)}
            </div>
          </>
          : <div className="watch-empty compact"><PlugsConnected /><strong>{!workspaceId ? "请选择一个项目" : oauthFeedLoadState === "error" ? "自动抓取状态读取失败" : "正在读取自动抓取快照"}</strong><p>{oauthFeedLoadState === "error" ? "本次读取未成功，无法确认三个来源是否有新内容；后台会按计划重试。" : "OAuth 上下文按 Workspace 隔离，并且只读取后台已有快照。"}</p></div>}
      </section>

      <section className="watch-card daily-panel">
        <div className="watch-card-heading"><div><span>ASIA/SHANGHAI · TODAY</span><h2>今日时间线与统计</h2></div><Pulse /></div>
        {statistics
          ? <>
            {historyLoadState === "error" && <ReadFailure title="今日时间线刷新失败" detail="当前显示上次成功读取的区间，并明确保留为旧读取结果。" />}
            <div className="watch-timeline" aria-label="今日时间线">
              {latestFirstTimeline.length
                ? <>
                  {latestFirstTimeline.some((item) => item.window_title || item.url) && <ActivityTextBoundary className="watch-timeline-boundary" />}
                  <ol>{latestFirstTimeline.map((item) => <li key={item.id} data-afk={item.afk_state}>
                    <time dateTime={item.started_at}>{formatTime(item.started_at)}</time>
                    <i />
                    <div><strong>{`${item.app_name ?? afkText(item.afk_state)} — ${formatDuration(item.duration_seconds)}`}</strong><span>{item.category ?? "未匹配 Category"} · {formatTime(item.ended_at)}</span>
                      {(item.window_title || item.url) && <UntrustedRecord>
                        {item.window_title && <p>{item.window_title}</p>}
                        {item.url && <code>{item.url}</code>}
                      </UntrustedRecord>}
                    </div>
                  </li>)}</ol>
                </>
                : <div className="watch-empty compact">今天还没有可展示的活动区间。</div>}
            </div>
            <div className="distribution-grid">
              <Distribution title="应用分布" values={statistics.app_seconds} icon={<AppWindow />} />
              <Distribution title="动态 Category" values={statistics.category_seconds} icon={<Stack />} footer={`规则版本 ${statistics.category_rule_version}`} />
            </div>
          </>
          : <div className="watch-empty"><WifiSlash /><strong>{historyLoadState === "loading" ? "正在读取今日活动…" : "今日时间线读取失败"}</strong><p>{historyLoadState === "loading" ? "正在查询今日 00:00 至当前的 ActivityWatch 事实。" : "本次读取未成功；历史总结和任务账本不受这个实时查询影响。"}</p></div>}
      </section>

      <section className="watch-card summaries-panel">
        <div className="watch-card-heading"><div><span>DERIVED LEDGER</span><h2>最近总结</h2></div><CalendarDots /></div>
        {summaryLoadState === "error" && <ReadFailure
          title="总结历史读取失败"
          detail={summaries.length ? "当前显示上次成功读取的总结；本次刷新失败。" : "暂时无法确认是否已有总结，不会把读取失败当作空历史。"}
        />}
        <div className="summary-layout">
          <article className={`summary-primary ${dailySummary ? "" : "empty"}`.trim()} aria-label="过去 24 小时主总结">
            <header><div><span>过去 24 小时</span><small>每日 06:00 固定边界</small></div>{dailySummary && <b data-finality={dailySummary.finality}>{dailySummary.finality === "final" ? "最终" : "临时"}</b>}</header>
            {dailySummary
              ? <>
                <p>{dailySummary.narrative}</p>
                <small><time dateTime={dailySummary.window_start}>{formatDateTime(dailySummary.window_start)}</time> – <time dateTime={dailySummary.window_end}>{formatDateTime(dailySummary.window_end)}</time></small>
                <SummaryTraceDetails summary={dailySummary} />
                <button
                  type="button"
                  className="watch-regenerate"
                  disabled={regeneratingTaskId !== null}
                  onClick={() => void regenerateTask(dailySummary.task_id)}
                >
                  <ArrowClockwise />
                  {regeneratingTaskId === dailySummary.task_id ? "正在提交…" : "重新生成"}
                </button>
              </>
              : <div className="summary-empty-copy"><Clock /><strong>{summaryLoadState === "loading" ? "正在读取过去 24 小时总结" : summaryLoadState === "error" ? "过去 24 小时总结暂不可确认" : "尚无过去 24 小时总结"}</strong><p>{summaryLoadState === "ready" ? "任务完成后，最新日总结会固定显示在这里。" : "等待派生总结账本恢复。"}</p></div>}
          </article>
          <div className="summary-secondary-region" role="region" aria-label="其他周期总结">
            <header><strong>其他周期</strong><span>阶段、周、双周与月</span></header>
            <div className="summary-secondary-grid">
              {secondarySummaryKinds.map((kind) => {
                const summary = latestByKind.get(kind);
                return <article key={kind} className={summary ? "" : "empty"} aria-label={`${summaryKindText[kind]}总结`}>
                  <header><span>{summaryKindText[kind]}</span>{summary && <b data-finality={summary.finality}>{summary.finality === "final" ? "最终" : "临时"}</b>}</header>
                  {summary
                    ? <>
                      <p>{summary.narrative}</p>
                      <small><time dateTime={summary.window_start}>{formatDateTime(summary.window_start)}</time> – <time dateTime={summary.window_end}>{formatDateTime(summary.window_end)}</time></small>
                      <SummaryTraceDetails summary={summary} />
                      <button
                        type="button"
                        className="watch-regenerate"
                        disabled={regeneratingTaskId !== null}
                        onClick={() => void regenerateTask(summary.task_id)}
                      >
                        <ArrowClockwise />
                        {regeneratingTaskId === summary.task_id ? "正在提交…" : "重新生成"}
                      </button>
                    </>
                    : <p>{summaryLoadState === "loading" ? "正在读取" : summaryLoadState === "error" ? "本次读取失败" : "尚无可展示总结"}</p>}
                </article>;
              })}
            </div>
          </div>
        </div>
        <section className="summary-history-region" role="region" aria-label="总结历史">
          <header><div><strong>总结历史</strong><span>旧窗口与同一任务的旧修订</span></div><b>{historicalSummaries.length} 条</b></header>
          {historicalSummaries.length
            ? <ol>{historicalSummaries.map((summary) => {
              const isOldRevision = latestByTask.get(summary.task_id)?.id !== summary.id;
              return <li key={summary.id}>
                <details>
                  <summary>
                    <div><strong>{summaryKindText[summary.kind]}</strong><span><time dateTime={summary.window_start}>{formatDateTime(summary.window_start)}</time> – <time dateTime={summary.window_end}>{formatDateTime(summary.window_end)}</time></span></div>
                    <span data-history-kind={isOldRevision ? "revision" : "window"}>{isOldRevision ? "同任务旧修订" : "历史窗口"}</span>
                    <b data-finality={summary.finality}>{summary.finality === "final" ? "最终" : "临时"}</b>
                  </summary>
                  <div className="summary-history-content">
                    <p>{summary.narrative}</p>
                    <small>生成于 <time dateTime={summary.completed_at}>{formatDateTime(summary.completed_at)}</time> · 任务 {compactReference(summary.task_id)} · 修订 {compactReference(summary.id)}</small>
                    <SummaryTraceDetails summary={summary} />
                  </div>
                </details>
              </li>;
            })}</ol>
            : summaryLoadState === "loading"
              ? <p>正在读取总结历史…</p>
              : summaryLoadState === "error"
                ? <p>总结历史读取失败，暂时无法确认是否有旧窗口或修订。</p>
                : <p>没有更多历史窗口或旧修订。</p>}
        </section>
      </section>

      <div className="watch-history-grid">
        <section className="watch-card trends-panel">
          <div className="watch-card-heading"><div><span>WEEK / MONTH</span><h2>长期趋势</h2></div><TrendUp /></div>
          {trendLoadState === "error" && (weeklyTrends.length > 0 || monthlyTrends.length > 0) && <ReadFailure title="趋势刷新失败" detail="当前保留上次成功读取的周/月趋势。" />}
          {weeklyTrends.length || monthlyTrends.length
            ? <div className="trend-series">
              <section><h3>周趋势</h3><TrendBars points={weeklyTrends} /></section>
              <section><h3>月趋势</h3><TrendBars points={monthlyTrends} /></section>
            </div>
            : <div className="watch-empty compact"><ChartBar /><strong>{trendLoadState === "loading" ? "正在读取趋势" : trendLoadState === "error" ? "趋势读取失败" : "趋势正在积累"}</strong><p>{trendLoadState === "error" ? "本次读取未成功，无法确认是否已有周/月趋势。" : "周与月边界固定后，这里会展示可追溯变化。"}</p></div>}
        </section>

        <section className="watch-card task-ledger">
          <div className="watch-card-heading"><div><span>RECOVERY</span><h2>补偿任务</h2></div><ListChecks /></div>
          <div className="task-counts"><span><Clock />待处理 {actionableTasks.length}</span><span className={failedTaskCount ? "failed" : ""}><WarningCircle />失败 {failedTaskCount}</span></div>
          {taskLoadState === "error" && tasks.length > 0 && <ReadFailure title="任务账本刷新失败" detail="当前显示上次成功读取的任务状态。" />}
          {regenerationError && <p className="watch-error" role="alert">{regenerationError}</p>}
          {actionableTasks.length
            ? <ol>{actionableTasks.map((task) => <li key={task.id}>
              <i data-status={task.status}>{task.status === "completed" ? <CheckCircle /> : <Clock />}</i>
              <div><strong>{summaryKindText[task.kind]}</strong><span>{formatDateTime(task.window_start)} – {formatDateTime(task.window_end)}</span><small>已尝试 {task.attempt_count} 次{task.next_attempt_at ? ` · 下次 ${formatDateTime(task.next_attempt_at)}` : ""}</small></div>
              <b data-status={task.status}>{taskStatusText[task.status]}</b>
              {task.error_code && <code>{task.error_code}</code>}
              {(task.status === "failed" || task.status === "needs_retry") && <button
                type="button"
                className="watch-regenerate task-action"
                disabled={regeneratingTaskId !== null}
                onClick={() => void regenerateTask(task.id)}
              >
                <ArrowClockwise />
                {regeneratingTaskId === task.id ? "提交中…" : "重试"}
              </button>}
            </li>)}</ol>
            : <div className="watch-empty compact">{taskLoadState === "ready" ? <CheckCircle /> : taskLoadState === "error" ? <WarningCircle /> : <Clock />}<strong>{taskLoadState === "loading" ? "正在读取任务账本" : taskLoadState === "error" ? "任务账本读取失败" : "没有待补任务"}</strong><p>{taskLoadState === "error" ? "本次读取未成功，无法确认是否存在待补或失败任务。" : "理论窗口均已完成或正在等待新的窗口结束。"}</p></div>}
        </section>
      </div>
    </div>
  </div>;
}

function TrendBars({ points }: { points: ActivityTrendPoint[] }) {
  if (!points.length) return <p className="trend-empty">暂无已完成窗口</p>;
  const maxSeconds = Math.max(1, ...points.map((point) => point.active_seconds));
  return <ol className="trend-bars">{points.map((point) => <li key={`${point.window_start}:${point.window_end}`}>
    <div><i style={{ height: `${Math.max(4, point.active_seconds / maxSeconds * 100)}%` }} /></div>
    <strong>{formatDuration(point.active_seconds)}</strong>
    <span>{point.dominant_category ?? "无主 Category"}</span>
    <small>{formatDateTime(point.window_start)}</small>
  </li>)}</ol>;
}

function Distribution({
  title,
  values,
  icon,
  footer,
}: {
  title: string;
  values: Record<string, number>;
  icon: React.ReactNode;
  footer?: string;
}) {
  const ranked = entries(values);
  const total = ranked.reduce((sum, [, seconds]) => sum + seconds, 0);
  return <section className="distribution-card">
    <header>{icon}<h3>{title}</h3></header>
    {ranked.length
      ? <ol>{ranked.slice(0, 8).map(([name, seconds]) => <li key={name}>
        <div><span>{`${name} — ${formatDuration(seconds)}`}</span><small>{total ? Math.round(seconds / total * 100) : 0}%</small></div>
        <i><b style={{ width: `${total ? seconds / total * 100 : 0}%` }} /></i>
      </li>)}</ol>
      : <p>暂无分布数据</p>}
    {footer && <footer>{footer}</footer>}
  </section>;
}
