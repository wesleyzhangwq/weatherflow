"use client";

import { useEffect, useState } from "react";
import { api, type EventRecord } from "@/lib/api";

/** 溯源弹层：展示一条 L1 事件的原始记录。
 *
 * 这是「evidence 必须可溯源」哲学的 UI 落点——任何 hypothesis 依据、
 * 任何语义记忆芯片，点开都能看到它指向的那条 append-only 事件。
 */
export function EvidenceModal({
  eventId,
  onClose
}: {
  eventId: string;
  onClose: () => void;
}) {
  const [record, setRecord] = useState<EventRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .event(eventId)
      .then((r) => !cancelled && setRecord(r))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg max-h-[80vh] overflow-auto rounded-xl bg-white dark:bg-neutral-900 border border-black/10 dark:border-white/15 shadow-xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest muted">
              L1 事件溯源
            </div>
            <div className="mt-1 font-mono text-xs muted break-all">{eventId}</div>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="rounded-md border border-black/10 dark:border-white/20 px-2 py-1 text-xs hover:bg-black/5 dark:hover:bg-white/10"
          >
            关闭 Esc
          </button>
        </div>

        {error && <p className="mt-4 text-sm text-red-600">无法溯源：{error}</p>}
        {!record && !error && <p className="mt-4 text-sm muted">加载中…</p>}

        {record && (
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full bg-black/5 dark:bg-white/10 px-2.5 py-0.5 text-xs">
                {record.type}
              </span>
              <span className="rounded-full bg-black/5 dark:bg-white/10 px-2.5 py-0.5 text-xs">
                {new Date(record.timestamp).toLocaleString("zh-CN", {
                  hour12: false
                })}
              </span>
            </div>

            <div>
              <div className="text-xs uppercase tracking-widest muted">payload</div>
              <dl className="mt-1.5 space-y-1.5">
                {Object.entries(record.payload).map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[7rem_1fr] gap-2">
                    <dt className="text-xs muted break-all pt-0.5">{k}</dt>
                    <dd className="whitespace-pre-wrap break-words">
                      {typeof v === "string" ? v : JSON.stringify(v, null, 1)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>

            {Object.keys(record.refs || {}).length > 0 && (
              <div>
                <div className="text-xs uppercase tracking-widest muted">refs</div>
                <pre className="mt-1 text-xs muted overflow-auto">
                  {JSON.stringify(record.refs, null, 1)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
