"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { MemoryFeedbackType, SemanticItem } from "@/lib/api";

const FEEDBACK_OPTIONS: { type: MemoryFeedbackType; label: string }[] = [
  { type: "accurate", label: "准确" },
  { type: "inaccurate", label: "不准确" },
  { type: "stale", label: "过期" },
  { type: "important", label: "重要" }
];

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
              className="leading-relaxed border-b border-black/5 dark:border-white/10 last:border-0 pb-3 last:pb-0"
            >
              <div className="flex items-start justify-between gap-4">
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
              </div>
              <MemoryFeedbackControls item={s} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MemoryFeedbackControls({ item }: { item: SemanticItem }) {
  const [done, setDone] = useState<MemoryFeedbackType | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const send = async (feedbackType: MemoryFeedbackType) => {
    setErr(null);
    try {
      await api.submitMemoryFeedback({
        semantic_key: item.key,
        feedback_type: feedbackType,
        semantic_value_snapshot: item.value,
        session_id: "default"
      });
      setDone(feedbackType);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {FEEDBACK_OPTIONS.map((option) => (
          <button
            key={option.type}
            type="button"
            onClick={() => void send(option.type)}
            className="rounded-full px-3 py-1 text-xs border border-black/15 dark:border-white/20 hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-60"
            disabled={done !== null}
          >
            {option.label}
          </button>
        ))}
      </div>
      {done ? (
        <p className="text-xs muted mt-1">已记录：{feedbackLabel(done)}</p>
      ) : null}
      {err ? (
        <p className="text-xs text-red-600 dark:text-red-400 mt-1">{err}</p>
      ) : null}
    </div>
  );
}

function feedbackLabel(type: MemoryFeedbackType) {
  return FEEDBACK_OPTIONS.find((option) => option.type === type)?.label ?? type;
}
