"use client";

import type { SemanticItem } from "@/lib/api";

export function UserModelCard({ items }: { items: SemanticItem[] }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">
        它对你的长期印象
      </div>
      {items.length === 0 ? (
        <div className="muted mt-3">
          还在听。多来几次签到，这里会慢慢有字。
        </div>
      ) : (
        <ul className="mt-4 space-y-3">
          {items.map((s) => (
            <li
              key={s.key}
              className="flex items-start justify-between gap-4 leading-relaxed"
            >
              <div>
                <div className="text-xs muted">{s.key}</div>
                <div>{s.value}</div>
              </div>
              <div
                title={`置信度 ${(s.confidence * 100).toFixed(0)}%`}
                className="shrink-0 mt-1 h-1.5 w-16 rounded-full bg-black/5 dark:bg-white/10 overflow-hidden"
              >
                <div
                  className="h-full bg-current opacity-60"
                  style={{ width: `${Math.round(s.confidence * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
