"use client";

import type { TimelineEvent } from "@/lib/api";

const KIND_ZH: Record<TimelineEvent["kind"], string> = {
  milestone: "里程碑",
  phase: "阶段",
  event: "事件"
};

export function GrowthTimeline({ items }: { items: TimelineEvent[] }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">成长时间线</div>
      {items.length === 0 ? (
        <div className="muted mt-3">
          你持续出现时，时间线会自己写下去。
        </div>
      ) : (
        <ol className="mt-5 relative border-l border-black/10 dark:border-white/10 pl-6 space-y-6">
          {items.map((e) => (
            <li key={e.id ?? `${e.ts}-${e.title}`} className="relative">
              <span className="absolute -left-[7px] top-2 w-3 h-3 rounded-full bg-current opacity-60" />
              <div className="text-xs muted">
                {e.ts} · {KIND_ZH[e.kind]}
              </div>
              <div className="font-serif text-lg mt-0.5">{e.title}</div>
              {e.description ? (
                <p className="mt-1 leading-relaxed">{e.description}</p>
              ) : null}
              {e.tags.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {e.tags.map((t) => (
                    <span
                      key={t}
                      className="text-xs px-2 py-0.5 rounded-full border border-black/10 dark:border-white/15"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
