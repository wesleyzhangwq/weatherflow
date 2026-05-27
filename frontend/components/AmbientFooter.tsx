"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type DashboardSnapshot, type HypothesisLabel } from "@/lib/api";
import { LABEL_GLYPH, LABEL_TEXT } from "@/lib/labels";

function formatAgo(min: number | null): string {
  if (min === null) return "尚未更新";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

export function AmbientFooter() {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(null);

  useEffect(() => {
    api.dashboardSnapshot().then(setSnap).catch(() => setSnap(null));
  }, []);

  if (!snap) return null;

  const labelCounts: Partial<Record<HypothesisLabel, number>> = {};
  for (const beat of snap.recent_rhythm) {
    if (beat.verdict === "confirmed") {
      labelCounts[beat.label] = (labelCounts[beat.label] || 0) + 1;
    }
  }
  const labelSummary = Object.entries(labelCounts)
    .sort((a, b) => b[1] - a[1])
    .map(
      ([label, count]) =>
        `${LABEL_TEXT[label as HypothesisLabel]} × ${count}`
    )
    .join(" · ");

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="card">
        <div className="text-xs uppercase tracking-widest muted">
          最近 7 天节奏（confirmed）
        </div>
        {snap.recent_rhythm.length === 0 ? (
          <p className="mt-3 text-sm muted">
            还没有节奏可看。做几次签到 + 校准，这里就会出现。
          </p>
        ) : (
          <>
            <div className="mt-3 flex gap-1.5 flex-wrap">
              {snap.recent_rhythm
                .slice()
                .reverse()
                .map((beat, i) => (
                  <span
                    key={i}
                    title={`${beat.label} · ${new Date(
                      beat.timestamp
                    ).toLocaleString("zh-CN")} · ${beat.verdict}`}
                    className={`inline-block w-7 h-7 leading-7 text-center rounded text-base ${
                      beat.verdict === "confirmed"
                        ? "bg-black/10 dark:bg-white/15"
                        : beat.verdict === "rejected"
                        ? "bg-red-500/20 line-through"
                        : "bg-black/5 dark:bg-white/5 opacity-60"
                    }`}
                  >
                    {LABEL_GLYPH[beat.label]}
                  </span>
                ))}
            </div>
            <p className="mt-3 text-xs muted">
              {labelSummary || "（还无已校准 confirmed 的判断）"}
            </p>
          </>
        )}
      </div>

      <div className="card">
        <div className="text-xs uppercase tracking-widest muted">
          长期画像快照
        </div>
        <div className="mt-3">
          <div className="text-xs muted mb-1">Active Projects</div>
          {snap.profile.active_projects_preview.length > 0 ? (
            <ul className="text-sm space-y-0.5">
              {snap.profile.active_projects_preview.map((p) => (
                <li key={p}>· {p}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm muted">（尚未识别活跃项目）</p>
          )}
        </div>
        <div className="mt-4 text-xs muted">
          上次画像更新：{formatAgo(snap.profile.last_patch_minutes_ago)}
        </div>
        <Link
          href="/profile"
          className="mt-3 inline-block text-xs underline decoration-dotted"
        >
          查看完整 profile.md →
        </Link>
      </div>
    </div>
  );
}
