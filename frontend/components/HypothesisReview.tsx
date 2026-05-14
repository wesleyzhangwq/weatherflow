"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { HypothesisFeedback, SensorHypothesis } from "@/lib/api";

export function HypothesisReview({
  items
}: {
  items: SensorHypothesis[];
}) {
  const [done, setDone] = useState<Record<number, HypothesisFeedback>>({});
  const [err, setErr] = useState<string | null>(null);

  const pending = items.filter((item) => !done[item.id]);
  if (items.length === 0) return null;

  const send = async (id: number, feedback: HypothesisFeedback) => {
    setErr(null);
    try {
      await api.submitHypothesisFeedback(id, feedback);
      setDone((prev) => ({ ...prev, [id]: feedback }));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">
        想跟你确认的弱信号
      </div>
      {pending.length === 0 ? (
        <p className="muted mt-3 text-sm">这些判断已经记录了你的反馈。</p>
      ) : (
        <ul className="mt-3 space-y-4">
          {pending.map((item) => (
            <li key={item.id}>
              <div className="font-medium">{item.label}</div>
              <p className="muted mt-1 text-sm leading-relaxed">{item.summary}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void send(item.id, "confirmed")}
                  className="rounded-full px-3 py-1 text-xs border border-black/15 dark:border-white/20 hover:bg-black/5 dark:hover:bg-white/10"
                >
                  准
                </button>
                <button
                  type="button"
                  onClick={() => void send(item.id, "rejected")}
                  className="rounded-full px-3 py-1 text-xs border border-black/15 dark:border-white/20 hover:bg-black/5 dark:hover:bg-white/10"
                >
                  不太对
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {err ? (
        <p className="text-sm text-red-600 dark:text-red-400 mt-2">{err}</p>
      ) : null}
    </div>
  );
}
