"use client";

import type { UserState } from "@/lib/api";
import { displayRationaleZh } from "@/lib/rationaleZh";
import { WEATHER_BLURB, WEATHER_GLYPH, WEATHER_LABEL_ZH } from "@/lib/weather";

export function WeatherCard({ state }: { state: UserState | null }) {
  if (!state) {
    return (
      <div className="card">
        <div className="text-sm muted">还没有读数。</div>
        <div className="mt-1">可以先做一次签到。</div>
      </div>
    );
  }
  const glyph = WEATHER_GLYPH[state.weather_label];
  const blurb = WEATHER_BLURB[state.weather_label];
  const zh = WEATHER_LABEL_ZH[state.weather_label];
  const rationaleZh = displayRationaleZh(state.rationale);
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
      {rationaleZh ? (
        <p className="mt-5 text-sm leading-relaxed">{rationaleZh}</p>
      ) : null}
    </div>
  );
}
