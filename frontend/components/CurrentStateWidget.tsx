"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type DashboardSnapshot } from "@/lib/api";
import {
  LABEL_GLYPH,
  LABEL_TEXT,
  WEATHER_SEMANTIC,
  WEATHER_TEXT,
  SOURCE_TAG_TEXT
} from "@/lib/labels";

function ago(min: number | null | undefined): string {
  if (min === null || min === undefined) return "刚刚";
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

function inMin(min: number | null | undefined): string {
  if (min === null || min === undefined) return "—";
  if (min < 60) return `${min} 分钟后`;
  const h = Math.floor(min / 60);
  return `${h} 小时后`;
}

const STATUS_BADGE: Record<string, { text: string; cls: string }> = {
  active: { text: "未校准", cls: "bg-black/10 dark:bg-white/10" },
  confirmed: {
    text: "✓ 已确认",
    cls: "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
  },
  rejected: {
    text: "✗ 已驳回",
    cls: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300"
  },
  partial: {
    text: "△ 部分准",
    cls: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
  },
  expired: {
    text: "⏳ 过期",
    cls: "bg-gray-200 dark:bg-gray-700 muted"
  }
};

export function CurrentStateWidget() {
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
      <div className="card text-sm muted">加载中…</div>
    );
  }

  const hyp = snap?.latest_hypothesis;
  const chk = snap?.latest_checkin;
  const nextCheck = snap?.scheduler?.next_check_minutes ?? null;

  return (
    <div className="card space-y-3">
      <div className="text-xs uppercase tracking-widest muted">当前节奏</div>

      {hyp ? (
        <div className="flex items-start gap-3">
          <span className="text-3xl leading-none">{LABEL_GLYPH[hyp.label]}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <h2 className="font-serif text-xl tracking-tight">
                {LABEL_TEXT[hyp.label]} · {hyp.label}
              </h2>
              <span className="text-xs muted">
                conf {(hyp.confidence * 100).toFixed(0)}%
              </span>
              <span
                className={`text-xs px-2 py-0.5 rounded ${
                  STATUS_BADGE[hyp.status]?.cls ?? "muted"
                }`}
              >
                {STATUS_BADGE[hyp.status]?.text ?? hyp.status}
              </span>
            </div>
            <p className="mt-1 text-sm">{hyp.summary}</p>
            <p className="mt-1 text-xs muted">
              来源：{SOURCE_TAG_TEXT[hyp.source_tag] || hyp.source_tag} ·{" "}
              {ago(hyp.minutes_ago)}
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm muted">
          还没有 hypothesis。
          <Link href="/checkin" className="underline ml-1">
            做一次签到
          </Link>
          ，或等定时检查到点。
        </p>
      )}

      <div className="border-t border-black/5 dark:border-white/10 pt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs uppercase tracking-widest muted mb-1">
            你最近一次签到
          </div>
          {chk ? (
            <div>
              <div>
                {WEATHER_TEXT[chk.weather]} ·{" "}
                <span className="muted text-xs">
                  {WEATHER_SEMANTIC[chk.weather]}
                </span>
              </div>
              <div className="text-xs muted mt-0.5">
                {ago(chk.minutes_ago)}
                {chk.project && ` · 项目 ${chk.project}`}
              </div>
            </div>
          ) : (
            <div className="text-sm muted">尚未签到</div>
          )}
        </div>

        <div>
          <div className="text-xs uppercase tracking-widest muted mb-1">
            下次自动评估
          </div>
          <div>{inMin(nextCheck)}</div>
          <div className="text-xs muted mt-0.5">
            T2 定时检查（每 6 小时一次）
          </div>
        </div>
      </div>
    </div>
  );
}
