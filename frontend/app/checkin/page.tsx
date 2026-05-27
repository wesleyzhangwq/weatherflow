"use client";

import { useState } from "react";
import Link from "next/link";
import {
  api,
  type CheckinIn,
  type Weather,
  type CheckinFriction,
  type HypothesisCard as HypCard
} from "@/lib/api";
import { WEATHER_SEMANTIC, WEATHER_TEXT } from "@/lib/labels";
import { HypothesisCard } from "@/components/HypothesisCard";

const WEATHERS: Weather[] = [
  "sunny",
  "partly_cloudy",
  "cloudy",
  "rainy",
  "thunderstorm",
  "foggy"
];
const FRICTIONS: { value: CheckinFriction; label: string }[] = [
  { value: "none", label: "（无）" },
  { value: "task_complexity", label: "任务复杂度超预期" },
  { value: "missing_info", label: "缺少信息或决策依赖" },
  { value: "context_switch", label: "频繁切换上下文" },
  { value: "external_block", label: "被外部阻塞" },
  { value: "energy", label: "精力不足" }
];

type Phase = "form" | "submitting" | "done" | "error";

const PROGRESS_STEPS = [
  "已记录签到",
  "装配 evidence bundle",
  "调用 LLM 生成 hypothesis"
];

export default function CheckinPage() {
  const [phase, setPhase] = useState<Phase>("form");
  const [weather, setWeather] = useState<Weather>("partly_cloudy");
  const [project, setProject] = useState("");
  const [friction, setFriction] = useState<CheckinFriction>("none");
  const [text, setText] = useState("");
  const [stepIdx, setStepIdx] = useState(0);
  const [card, setCard] = useState<HypCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPhase("submitting");
    setError(null);
    setStepIdx(0);

    // Light-weight progress simulation: advance through the 3 stages while
    // the sync API runs. Real backend timing is ~2-5s for LLM, so this gives
    // the user something to watch.
    const stepTimers = [
      setTimeout(() => setStepIdx(1), 300),
      setTimeout(() => setStepIdx(2), 1000)
    ];

    const body: CheckinIn = {
      weather,
      project: project.trim() || null,
      friction_point: friction === "none" ? null : friction,
      free_text: text.trim() || null
    };

    try {
      const res = await api.submitCheckin(body);
      stepTimers.forEach(clearTimeout);
      // Backend returns a HypothesisPayload (no status field). Card view
      // needs status='active' so the calibrate buttons render.
      const fullCard: HypCard = {
        id: res.hypothesis_id,
        timestamp: new Date().toISOString(),
        label: res.hypothesis.label,
        confidence: res.hypothesis.confidence,
        summary: res.hypothesis.summary,
        evidence: res.hypothesis.evidence,
        counter_evidence: res.hypothesis.counter_evidence ?? [],
        missing_evidence: res.hypothesis.missing_evidence ?? [],
        source_tag: res.hypothesis.source_tag,
        conversation_id: res.hypothesis.conversation_id ?? null,
        status: "active"
      };
      setCard(fullCard);
      setStepIdx(PROGRESS_STEPS.length);
      setPhase("done");
    } catch (err) {
      stepTimers.forEach(clearTimeout);
      setError((err as Error).message);
      setPhase("error");
    }
  }

  function resetForm() {
    setPhase("form");
    setCard(null);
    setStepIdx(0);
    setText("");
    setFriction("none");
    setProject("");
    setError(null);
  }

  return (
    <div className="space-y-6 max-w-xl mx-auto">
      <div>
        <div className="text-xs uppercase tracking-widest muted">签到 · T1</div>
        <h1 className="mt-2 font-serif text-3xl tracking-tight">现在感觉怎样？</h1>
        <p className="mt-1 text-sm muted">
          三问：天气必填；项目、摩擦点和自由文本可选。一天可以做多次。
        </p>
      </div>

      {phase !== "done" && (
        <form
          className={`card space-y-5 transition-opacity ${
            phase === "submitting" ? "opacity-60 pointer-events-none" : ""
          }`}
          onSubmit={onSubmit}
        >
          <div>
            <div className="text-xs uppercase tracking-widest muted">天气</div>
            <div className="mt-2 grid grid-cols-3 md:grid-cols-6 gap-2">
              {WEATHERS.map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => setWeather(w)}
                  title={WEATHER_SEMANTIC[w]}
                  className={`rounded-md border px-2 py-3 text-sm ${
                    weather === w
                      ? "border-black dark:border-white"
                      : "border-black/10 dark:border-white/20"
                  }`}
                >
                  {WEATHER_TEXT[w]}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs muted">
              {WEATHER_TEXT[weather]} · {WEATHER_SEMANTIC[weather]}
            </p>
          </div>

          <div>
            <label className="text-xs uppercase tracking-widest muted" htmlFor="project">
              项目（可选）
            </label>
            <input
              id="project"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              placeholder="weatherflow"
              className="mt-2 w-full rounded-md border border-black/10 dark:border-white/20 bg-transparent px-3 py-2"
            />
          </div>

          <div>
            <div className="text-xs uppercase tracking-widest muted">摩擦点（可选）</div>
            <select
              value={friction}
              onChange={(e) => setFriction(e.target.value as CheckinFriction)}
              className="mt-2 w-full rounded-md border border-black/10 dark:border-white/20 bg-transparent px-3 py-2"
            >
              {FRICTIONS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs uppercase tracking-widest muted" htmlFor="free">
              自由文本（可选）
            </label>
            <textarea
              id="free"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="今天卡在 RAG / 准备晚上跑一组实验 / …"
              className="mt-2 w-full rounded-md border border-black/10 dark:border-white/20 bg-transparent px-3 py-2"
            />
          </div>

          {phase === "error" && (
            <p className="text-sm text-red-600">提交失败：{error}</p>
          )}

          <button
            type="submit"
            disabled={phase === "submitting"}
            className="w-full rounded-md bg-black px-4 py-2 text-white dark:bg-white dark:text-black disabled:opacity-60"
          >
            {phase === "submitting"
              ? "提交中…"
              : "提交签到 · 触发 hypothesis 生成"}
          </button>
        </form>
      )}

      {phase === "submitting" && <ProgressLane currentStep={stepIdx} />}

      {phase === "done" && card && (
        <div className="space-y-4">
          <div className="rounded-md bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-500/30 px-4 py-2.5 text-sm">
            ✓ 已生成判断：<b>{card.label}</b> · conf{" "}
            {(card.confidence * 100).toFixed(0)}% · 回主页校准
          </div>

          {/* Read-only preview of the freshly generated hypothesis.
             Calibration happens on the home page (see CurrentStateWidget) —
             this keeps check-in submission feedback simple and one-directional. */}
          <HypothesisCard card={card} isTop={false} onCalibrated={() => {}} />

          <div className="flex gap-2">
            <button
              type="button"
              onClick={resetForm}
              className="flex-1 rounded-md border border-black/10 dark:border-white/20 px-4 py-2"
            >
              再签一次
            </button>
            <Link
              href="/"
              className="flex-1 text-center rounded-md bg-black px-4 py-2 text-white dark:bg-white dark:text-black"
            >
              回主页
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function ProgressLane({ currentStep }: { currentStep: number }) {
  return (
    <div className="card space-y-2 text-sm">
      {PROGRESS_STEPS.map((label, i) => {
        const done = i < currentStep;
        const active = i === currentStep;
        return (
          <div key={i} className="flex items-center gap-2">
            <span
              className={
                done
                  ? "text-emerald-600"
                  : active
                  ? "text-black dark:text-white"
                  : "muted"
              }
            >
              {done ? "✓" : active ? "⏳" : "·"}
            </span>
            <span
              className={
                done
                  ? "text-emerald-600"
                  : active
                  ? ""
                  : "muted"
              }
            >
              {label}
              {active && "…"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
