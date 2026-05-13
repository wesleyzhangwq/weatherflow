"use client";

import type { StateTrendPoint } from "@/lib/api";

export function FocusTrend({ points }: { points: StateTrendPoint[] }) {
  if (!points.length) {
    return (
      <div className="card">
        <div className="text-xs uppercase tracking-widest muted">专注度走势</div>
        <div className="muted mt-3">数据还不够画出趋势。</div>
      </div>
    );
  }
  const w = 320;
  const h = 90;
  const pad = 6;
  const xs = points.map(
    (_, i) => pad + (i * (w - pad * 2)) / Math.max(1, points.length - 1)
  );
  const ys = points.map((p) => h - pad - (p.focus / 100) * (h - pad * 2));
  const d = xs
    .map((x, i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${ys[i].toFixed(1)}`)
    .join(" ");

  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">专注度走势</div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="mt-3 w-full h-24"
        preserveAspectRatio="none"
      >
        <path
          d={d}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeOpacity="0.7"
        />
        {xs.map((x, i) => (
          <circle key={i} cx={x} cy={ys[i]} r="2" fill="currentColor" opacity="0.6" />
        ))}
      </svg>
      <div className="muted text-xs mt-2">最近 {points.length} 次快照</div>
    </div>
  );
}
