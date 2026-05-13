"use client";

import type { UserState } from "@/lib/api";
import { WEATHER_BLURB, WEATHER_GLYPH, WEATHER_LABEL_ZH } from "@/lib/weather";

export function WeatherCard({ state }: { state: UserState | null }) {
  if (!state) {
    return (
      <div className="card">
        <div className="text-sm muted">还没有读数。</div>
        <div className="mt-1">可以先做一次晨间签到。</div>
      </div>
    );
  }
  const glyph = WEATHER_GLYPH[state.weather_label];
  const blurb = WEATHER_BLURB[state.weather_label];
  const zh = WEATHER_LABEL_ZH[state.weather_label];
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">今日天气</div>
      <div className="mt-3 flex items-baseline gap-4">
        <div className="text-6xl leading-none">{glyph}</div>
        <div>
          <div className="font-serif text-3xl">{zh}</div>
          <div className="text-xs muted mt-0.5">{state.weather_label}</div>
          <div className="muted mt-1">{blurb}</div>
        </div>
      </div>
      {state.rationale ? (
        <p className="mt-5 text-sm leading-relaxed">{state.rationale}</p>
      ) : null}
    </div>
  );
}
