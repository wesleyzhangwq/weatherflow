"use client";

import { useEffect, useState } from "react";
import { api, type DashboardSnapshot } from "@/lib/api";
import Link from "next/link";

function formatAgo(min: number | null): string {
  if (min === null) return "—";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

function formatIn(min: number | null): string {
  if (min === null) return "—";
  if (min < 60) return `${min} 分钟`;
  const h = Math.floor(min / 60);
  return `${h}h${min % 60 > 0 ? ` ${min % 60}m` : ""}`;
}

export function DataStrip() {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .dashboardSnapshot()
      .then(setSnap)
      .catch(() => setSnap(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="card grid grid-cols-2 md:grid-cols-4 gap-3 text-xs muted">
        <span>加载中…</span>
      </div>
    );
  }
  if (!snap) {
    return (
      <div className="card text-xs muted">
        ⚠ 无法加载 dashboard 数据。后端是否在跑？
      </div>
    );
  }

  return (
    <div className="card grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
      <Metric
        icon="📅"
        label="今日会议"
        value={
          snap.today_calendar.has_data
            ? `${snap.today_calendar.event_count} 场`
            : "暂无数据"
        }
        sub={
          snap.today_calendar.has_data
            ? snap.today_calendar.total_minutes
              ? `${snap.today_calendar.total_minutes} 分钟`
              : "（无会议）"
            : "等待首次定时检查"
        }
      />
      <Metric
        icon="⌨"
        label={
          snap.this_week_github.has_data
            ? `近 ${snap.this_week_github.window_days} 天提交`
            : "GitHub"
        }
        value={
          snap.this_week_github.has_data
            ? `${snap.this_week_github.commits} commits`
            : "暂无数据"
        }
        sub={
          snap.this_week_github.has_data
            ? snap.this_week_github.active_repos.length
              ? `活跃 repo: ${snap.this_week_github.active_repos
                  .map((r) => r.split("/").pop())
                  .join(" · ")}`
              : "（窗口内无活动）"
            : "等待首次定时检查"
        }
      />
      <Metric
        icon="⏰"
        label="定时检查"
        value={
          snap.scheduler.last_check_at
            ? `上次 ${formatAgo(snap.scheduler.last_check_minutes_ago)}`
            : "尚未运行"
        }
        sub={
          snap.scheduler.next_check_minutes !== null
            ? `下次约 ${formatIn(snap.scheduler.next_check_minutes)}后`
            : "—"
        }
      />
      <ProposalsTile count={snap.pending_proposals_count} />
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  sub
}: {
  icon: string;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest muted">
        {icon} {label}
      </div>
      <div className="mt-1.5 font-medium">{value}</div>
      {sub && <div className="text-xs muted mt-0.5">{sub}</div>}
    </div>
  );
}

function ProposalsTile({ count }: { count: number }) {
  const body = (
    <>
      <div className="text-xs uppercase tracking-widest muted">💬 待确认</div>
      <div className="mt-1.5 font-medium">
        {count} 个 Proposal
      </div>
      <div className="text-xs muted mt-0.5">
        {count > 0 ? "去对话页确认 →" : "（无）"}
      </div>
    </>
  );
  return count > 0 ? (
    <Link href="/chat" className="hover:opacity-80">
      {body}
    </Link>
  ) : (
    <div>{body}</div>
  );
}
