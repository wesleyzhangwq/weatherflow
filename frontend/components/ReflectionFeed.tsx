"use client";

import { ReflectionGrounding } from "@/components/ReflectionGrounding";
import type { Reflection } from "@/lib/api";

const KIND_ZH: Record<Reflection["kind"], string> = {
  daily: "日间",
  weekly: "周间"
};

export function ReflectionFeed({ items }: { items: Reflection[] }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">最近反思</div>
      {items.length === 0 ? (
        <div className="muted mt-3">还没有反思记录。</div>
      ) : (
        <ul className="mt-4 space-y-5">
          {items.map((r) => (
            <li key={r.id} className="border-l-2 border-black/10 dark:border-white/10 pl-4">
              <div className="text-xs muted">
                {KIND_ZH[r.kind]} · {r.date}
              </div>
              <p className="mt-1 leading-relaxed whitespace-pre-wrap">{r.content}</p>
              <ReflectionGrounding sources={r.insights?.grounding_sources} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
