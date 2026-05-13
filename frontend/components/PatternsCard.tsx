"use client";

import type { PatternHit } from "@/lib/api";
import {
  patternExplainZh,
  patternLabelZh,
  SEVERITY_ZH
} from "@/lib/patternZh";

const SEV_BADGE: Record<PatternHit["severity"], string> = {
  info: "border-emerald-400/40 text-emerald-700 dark:text-emerald-300",
  watch: "border-amber-400/50 text-amber-700 dark:text-amber-300",
  alert: "border-rose-400/60 text-rose-700 dark:text-rose-300"
};

export function PatternsCard({ patterns }: { patterns: PatternHit[] }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">
        本周模式
      </div>
      <p className="text-sm muted mt-2">
        由本地行为数据算出的信号。每日「轻轻的一句」会尽量与这些信号呼应（不是机械引用）。
      </p>
      {patterns.length === 0 ? (
        <div className="muted mt-3">
          这周没有特别突出的模式。安静也很好。
        </div>
      ) : (
        <ul className="mt-4 space-y-4">
          {patterns.map((p) => (
            <li key={p.code} className="leading-relaxed">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-xs px-2 py-0.5 rounded-full border ${SEV_BADGE[p.severity]}`}
                >
                  {SEVERITY_ZH[p.severity] ?? p.severity}
                </span>
                <span className="font-medium">
                  {patternLabelZh(p.code, p.label)}
                </span>
              </div>
              <p className="mt-1 text-sm muted">
                {patternExplainZh(p.code, p.explanation)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
