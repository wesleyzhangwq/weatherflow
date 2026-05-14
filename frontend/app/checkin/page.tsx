"use client";

import { useState } from "react";
import { HypothesisReview } from "@/components/HypothesisReview";
import { ReflectionGrounding } from "@/components/ReflectionGrounding";
import { SuggestionFeedback } from "@/components/SuggestionFeedback";
import { api, type CheckinResponse } from "@/lib/api";
import { patternExplainZh, patternLabelZh } from "@/lib/patternZh";
import { displayRationaleZh } from "@/lib/rationaleZh";
import { WEATHER_BLURB, WEATHER_GLYPH, WEATHER_LABEL_ZH } from "@/lib/weather";

const WEATHER_OPTIONS = [
  "☀ 清晰 / 有动力",
  "⛅ 普通 / 稳定",
  "☁ 有点乱 / 分散",
  "🌧 压力大 / 疲惫",
  "⛈ 失控 / 焦虑"
] as const;

export default function CheckinPage() {
  const [weatherChoice, setWeatherChoice] = useState("");
  const [intention, setIntention] = useState("");
  const [blocker, setBlocker] = useState("");
  const [completed, setCompleted] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CheckinResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const data = await api.submitCheckin({
        status: weatherChoice || null,
        raw: intention.trim()
          ? `today_intention: ${intention.trim()}`
          : null,
        stuck_on: blocker.trim() || null,
        did_today: completed.trim() || null,
        anxiety: null
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
    const rationaleZh = displayRationaleZh(result.state.rationale);
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
          {rationaleZh && (
            <p className="mt-3 leading-relaxed">{rationaleZh}</p>
          )}
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">反思</div>
          <p className="mt-3 leading-relaxed whitespace-pre-wrap">
            {result.reflection.content}
          </p>
          <ReflectionGrounding
            sources={result.reflection.insights?.grounding_sources}
          />
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
        <HypothesisReview items={result.pending_hypotheses ?? []} />
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
      <h1 className="font-serif text-4xl">签到</h1>
      <p className="muted">四个短问题，大约 1～3 分钟。不想答的可以空着。</p>

      <div>
        <div className="block text-sm muted mb-2">今天天气怎么样？</div>
        <div className="muted mb-3 text-sm">你现在整体更像：</div>
        <div className="flex flex-wrap gap-2">
          {WEATHER_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() =>
                setWeatherChoice((cur) => (cur === opt ? "" : opt))
              }
              className={`rounded-full border px-3 py-2 text-sm leading-snug transition-colors ${
                weatherChoice === opt
                  ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
                  : "border-black/15 bg-white/60 dark:border-white/20 dark:bg-white/5 hover:border-black/30 dark:hover:border-white/40"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm muted mb-2" htmlFor="intention">
          今天最想完成的任务是什么？
        </label>
        <textarea
          id="intention"
          rows={2}
          value={intention}
          onChange={(e) => setIntention(e.target.value)}
          className="w-full rounded-2xl border border-black/10 dark:border-white/15 bg-white/60 dark:bg-white/5 px-4 py-3 leading-relaxed focus:outline-none focus:ring-2 focus:ring-black/20 dark:focus:ring-white/30"
          placeholder="（可选）"
        />
      </div>

      <div>
        <label className="block text-sm muted mb-2" htmlFor="blocker">
          今天最可能拖住你的任务是什么？
        </label>
        <textarea
          id="blocker"
          rows={2}
          value={blocker}
          onChange={(e) => setBlocker(e.target.value)}
          className="w-full rounded-2xl border border-black/10 dark:border-white/15 bg-white/60 dark:bg-white/5 px-4 py-3 leading-relaxed focus:outline-none focus:ring-2 focus:ring-black/20 dark:focus:ring-white/30"
          placeholder="（可选）"
        />
      </div>

      <div>
        <label className="block text-sm muted mb-2" htmlFor="completed">
          今天已经完成了什么？
        </label>
        <textarea
          id="completed"
          rows={2}
          value={completed}
          onChange={(e) => setCompleted(e.target.value)}
          className="w-full rounded-2xl border border-black/10 dark:border-white/15 bg-white/60 dark:bg-white/5 px-4 py-3 leading-relaxed focus:outline-none focus:ring-2 focus:ring-black/20 dark:focus:ring-white/30"
          placeholder="（可选）"
        />
      </div>

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
