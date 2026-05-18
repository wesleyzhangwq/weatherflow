import { BurnoutIndicator } from "@/components/BurnoutIndicator";
import { DevReviewPanel } from "@/components/DevReviewPanel";
import { MomentumGauge } from "@/components/MomentumGauge";
import { HypothesisReview } from "@/components/HypothesisReview";
import { ReflectionFeed } from "@/components/ReflectionFeed";
import { WeatherCard } from "@/components/WeatherCard";
import { API_BASE } from "@/lib/api";
import type {
  DevReview,
  DevReviewProviderReadiness,
  ProfileOut,
  Reflection,
  SensorHypothesis,
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
  const [state, reflections, profile, hypotheses, devReview, devReviewProviders] =
    await Promise.all([
      fetchOk<UserState>("/api/state/current"),
      fetchOk<Reflection[]>("/api/reflection?limit=3"),
      fetchOk<ProfileOut>("/api/memory/profile"),
      fetchOk<SensorHypothesis[]>("/api/sensors/hypotheses?status=pending&limit=5"),
      fetchOk<DevReview>("/api/dev-review/runs/latest"),
      fetchOk<DevReviewProviderReadiness[]>("/api/dev-review/providers")
    ]);
  const latestSuggestion = reflections?.[0]?.insights?.suggestion;

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
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">下一步建议</div>
          <p className="mt-3 leading-relaxed">
            {latestSuggestion || "还没有建议。先做一次签到，WF 会给你一句很轻的下一步。"}
          </p>
        </div>
      </section>

      <section>
        <DevReviewPanel
          initial={devReview}
          providers={devReviewProviders ?? []}
        />
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">长期画像</div>
          <pre className="mt-3 whitespace-pre-wrap text-sm leading-relaxed font-sans max-h-80 overflow-auto">
            {profile?.markdown || "profile.md 还没有建立。"}
          </pre>
        </div>
        <HypothesisReview items={hypotheses ?? []} />
      </section>

      <section>
        <ReflectionFeed items={reflections ?? []} />
      </section>
    </div>
  );
}
