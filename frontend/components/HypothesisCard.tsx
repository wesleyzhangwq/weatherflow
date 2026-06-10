"use client";

import { useState } from "react";
import { api, type HypothesisCard as Card } from "@/lib/api";
import { EvidenceModal } from "./EvidenceModal";
import { LABEL_GLYPH, LABEL_TEXT, SOURCE_TAG_TEXT } from "@/lib/labels";

export function HypothesisCard({
  card,
  isTop,
  onCalibrated
}: {
  card: Card;
  isTop: boolean;
  onCalibrated: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function calibrate(verdict: "confirmed" | "rejected" | "partial") {
    if (busy) return;
    setBusy(true);
    try {
      await api.submitFeedback(card.id, verdict);
      onCalibrated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between text-xs muted">
        <span>
          🏷 来源: {SOURCE_TAG_TEXT[card.source_tag] || card.source_tag} ·{" "}
          {new Date(card.timestamp).toLocaleString("zh-CN", { hour12: false })}
        </span>
        <span>conf {(card.confidence * 100).toFixed(0)}%</span>
      </div>

      <div className="mt-3 flex items-baseline gap-3">
        <span className="text-2xl">{LABEL_GLYPH[card.label]}</span>
        <h3 className="font-serif text-2xl tracking-tight">
          {LABEL_TEXT[card.label]} · {card.label}
        </h3>
      </div>

      <p className="mt-2 leading-relaxed">{card.summary}</p>

      <Section title="依据">
        {card.evidence.map((e, i) => (
          <EvidenceLine key={i} text={e.text} eventId={e.source_event_id} />
        ))}
      </Section>

      {card.counter_evidence.length > 0 && (
        <Section title="反方证据">
          {card.counter_evidence.map((e, i) => (
            <EvidenceLine key={i} text={e.text} eventId={e.source_event_id} />
          ))}
        </Section>
      )}

      {card.missing_evidence.length > 0 && (
        <Section title="缺少的信息">
          {card.missing_evidence.map((t, i) => (
            <li key={i} className="text-sm muted">
              · {t}
            </li>
          ))}
        </Section>
      )}

      {isTop && (
        <div className="mt-5 flex gap-2">
          <CalButton onClick={() => calibrate("confirmed")} disabled={busy}>
            准
          </CalButton>
          <CalButton onClick={() => calibrate("partial")} disabled={busy}>
            部分准
          </CalButton>
          <CalButton onClick={() => calibrate("rejected")} disabled={busy}>
            不准
          </CalButton>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className="text-xs uppercase tracking-widest muted">{title}</div>
      <ul className="mt-2 space-y-1">{children}</ul>
    </div>
  );
}

function EvidenceLine({ text, eventId }: { text: string; eventId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="text-sm flex items-start gap-2">
      <span className="flex-1">· {text}</span>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs muted underline decoration-dotted shrink-0"
        title={`查看来源事件 ${eventId}`}
      >
        溯源
      </button>
      {open && <EvidenceModal eventId={eventId} onClose={() => setOpen(false)} />}
    </li>
  );
}

function CalButton({
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className="rounded-md border border-black/10 dark:border-white/20 px-3 py-1.5 text-sm hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-50"
      {...rest}
    >
      {children}
    </button>
  );
}
