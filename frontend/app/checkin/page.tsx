"use client";

import { useState } from "react";
import { SuggestionFeedback } from "@/components/SuggestionFeedback";
import { api, type CheckinResponse } from "@/lib/api";
import {
  patternExplainZh,
  patternLabelZh
} from "@/lib/patternZh";
import { WEATHER_BLURB, WEATHER_GLYPH, WEATHER_LABEL_ZH } from "@/lib/weather";

const QUESTIONS = [
  { key: "status", q: "今天整体怎么样？用一句话说说。" },
  { key: "did_today", q: "你实际做了什么？" },
  { key: "stuck_on", q: "现在卡在哪里？" },
  { key: "anxiety", q: "心里挂着什么 / 在担心什么？" }
] as const;

type Field = (typeof QUESTIONS)[number]["key"];

export default function CheckinPage() {
  const [values, setValues] = useState<Record<Field, string>>({
    status: "",
    did_today: "",
    stuck_on: "",
    anxiety: ""
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CheckinResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const data = await api.submitCheckin({
        status: values.status || null,
        did_today: values.did_today || null,
        stuck_on: values.stuck_on || null,
        anxiety: values.anxiety || null
      });
      setResult(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    const glyph = WEATHER_GLYPH[result.state.weather_label];
    const zhLabel = WEATHER_LABEL_ZH[result.state.weather_label];
    const blurb = WEATHER_BLURB[result.state.weather_label];
    return (
      <div className="space-y-6">
        <h1 className="font-serif text-4xl">谢谢你愿意坐下来写这几句。</h1>
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">今日天气</div>
          <div className="mt-3 flex items-baseline gap-4">
            <span className="text-5xl">{glyph}</span>
            <div>
              <span className="font-serif text-3xl">{zhLabel}</span>
              <span className="text-sm muted ml-2">({result.state.weather_label})</span>
              <p className="muted mt-1 text-sm">{blurb}</p>
            </div>
          </div>
          {result.state.rationale && (
            <p className="mt-3 leading-relaxed">{result.state.rationale}</p>
          )}
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">反思</div>
          <p className="mt-3 leading-relaxed whitespace-pre-wrap">
            {result.reflection.content}
          </p>
        </div>
        {result.patterns && result.patterns.length > 0 ? (
          <div className="card">
            <div className="text-xs uppercase tracking-widest muted">
              本周模式（建议会参考这些信号）
            </div>
            <ul className="mt-3 space-y-2 text-sm">
              {result.patterns.map((p) => (
                <li key={p.code}>
                  <span className="font-medium">
                    {patternLabelZh(p.code, p.label)}
                  </span>
                  <p className="muted mt-0.5">
                    {patternExplainZh(p.code, p.explanation)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result.suggestion ? (
          <div className="card">
            <div className="text-xs uppercase tracking-widest muted">
              轻轻的一句（结合状态与上方模式信号）
            </div>
            <p className="mt-3 leading-relaxed">{result.suggestion}</p>
            <SuggestionFeedback
              suggestionText={result.suggestion}
              patternCodes={result.suggestion_pattern_codes ?? []}
              reflectionId={result.reflection.id}
            />
          </div>
        ) : null}
        <div>
          <a href="/" className="underline underline-offset-4">回到今日</a>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <h1 className="font-serif text-4xl">晨间签到</h1>
      <p className="muted">四个短问题，大约 1～3 分钟。不想答的可以空着。</p>

      {QUESTIONS.map(({ key, q }) => (
        <div key={key}>
          <label className="block text-sm muted mb-2">{q}</label>
          <textarea
            rows={2}
            value={values[key]}
            onChange={(e) =>
              setValues((v) => ({ ...v, [key]: e.target.value }))
            }
            className="w-full rounded-2xl border border-black/10 dark:border-white/15 bg-white/60 dark:bg-white/5 px-4 py-3 leading-relaxed focus:outline-none focus:ring-2 focus:ring-black/20 dark:focus:ring-white/30"
            placeholder="（可选）"
          />
        </div>
      ))}

      {error && (
        <div className="text-sm text-red-600 dark:text-red-400">{error}</div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-full px-6 py-2 bg-black text-white dark:bg-white dark:text-black disabled:opacity-50"
      >
        {submitting ? "正在聆听…" : "提交"}
      </button>
    </form>
  );
}
