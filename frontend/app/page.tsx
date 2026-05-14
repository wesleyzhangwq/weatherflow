import { BurnoutIndicator } from "@/components/BurnoutIndicator";
import { FocusTrend } from "@/components/FocusTrend";
import { GrowthTimeline } from "@/components/GrowthTimeline";
import { MomentumGauge } from "@/components/MomentumGauge";
import { PatternsCard } from "@/components/PatternsCard";
import { ReflectionFeed } from "@/components/ReflectionFeed";
import { UserModelCard } from "@/components/UserModelCard";
import { WeatherCard } from "@/components/WeatherCard";
import { API_BASE } from "@/lib/api";
import type {
  PatternReport,
  Reflection,
  SemanticItem,
  StateTrendPoint,
  TimelineEvent,
  UserState
} from "@/lib/api";

async function fetchOk<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export default async function Home() {
  const [state, trend, reflections, timeline, semantic, patterns] =
    await Promise.all([
      fetchOk<UserState>("/api/state/current"),
      fetchOk<StateTrendPoint[]>("/api/state/trend?days=14"),
      fetchOk<Reflection[]>("/api/reflection?limit=3"),
      fetchOk<TimelineEvent[]>("/api/timeline?limit=10"),
      fetchOk<SemanticItem[]>("/api/memory/semantic?limit=8"),
      fetchOk<PatternReport>("/api/state/patterns?window_days=7")
    ]);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="font-serif text-4xl tracking-tight">今日</h1>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div className="md:col-span-2">
          <WeatherCard state={state} />
        </div>
        <MomentumGauge value={state?.momentum ?? 0} />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <BurnoutIndicator value={state?.burnout ?? 0} />
        <FocusTrend points={trend ?? []} />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <PatternsCard patterns={patterns?.patterns ?? []} />
        <UserModelCard items={semantic ?? []} />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <ReflectionFeed items={reflections ?? []} />
        <GrowthTimeline items={timeline ?? []} />
      </section>
    </div>
  );
}
