import { BurnoutIndicator } from "@/components/BurnoutIndicator";
import { DevReviewPanel } from "@/components/DevReviewPanel";
import { MomentumGauge } from "@/components/MomentumGauge";
import { ReflectionFeed } from "@/components/ReflectionFeed";
import { WeatherCard } from "@/components/WeatherCard";
import { API_BASE } from "@/lib/api";
import type {
  DevReview,
  DevReviewProviderReadiness,
  ProfileOut,
  Reflection,
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
  const [
    state,
    reflections,
    profile,
    devReview,
    devReviewHistory,
    devReviewProviders
  ] =
    await Promise.all([
      fetchOk<UserState>("/api/state/current"),
      fetchOk<Reflection[]>("/api/reflection?limit=3"),
      fetchOk<ProfileOut>("/api/memory/profile"),
      fetchOk<DevReview>("/api/dev-review/runs/latest"),
      fetchOk<DevReview[]>("/api/dev-review/runs?limit=5"),
      fetchOk<DevReviewProviderReadiness[]>("/api/dev-review/providers")
    ]);
  const latestSuggestion = reflections?.[0]?.insights?.suggestion;

  return (
    <div className="space-y-7">
      <section className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest muted">WeatherFlow</div>
          <h1 className="mt-2 font-serif text-4xl tracking-tight">开发节奏</h1>
        </div>
        <a
          href="/checkin"
          className="w-fit rounded-lg bg-black px-4 py-2 text-sm text-white dark:bg-white dark:text-black"
        >
          签到
        </a>
      </section>

      <section className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <div className="md:col-span-2">
          <WeatherCard state={state} />
        </div>
        <MomentumGauge value={state?.momentum ?? 0} />
      </section>

      <section className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <BurnoutIndicator value={state?.burnout ?? 0} />
        <div className="card md:col-span-2">
          <div className="text-xs uppercase tracking-widest muted">下一步建议</div>
          <p className="mt-3 leading-relaxed">
            {latestSuggestion || "还没有建议。先做一次签到，WF 会给你一句很轻的下一步。"}
          </p>
        </div>
      </section>

      <section>
        <DevReviewPanel
          initial={devReview}
          history={devReviewHistory ?? []}
          providers={devReviewProviders ?? []}
        />
      </section>

      <section className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">长期画像</div>
          <pre className="mt-3 whitespace-pre-wrap text-sm leading-relaxed font-sans max-h-80 overflow-auto">
            {profile?.markdown || "profile.md 还没有建立。"}
          </pre>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-widest muted">证据来源</div>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-start justify-between gap-4">
              <dt className="font-medium">Check-in</dt>
              <dd className="muted text-right">用户主动输入，当日状态主信号</dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="font-medium">GitHub MCP</dt>
              <dd className="muted text-right">PR、issue、review 与仓库活动</dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="font-medium">Google Calendar MCP</dt>
              <dd className="muted text-right">会议负载与专注窗口</dd>
            </div>
          </dl>
        </div>
      </section>

      <section>
        <ReflectionFeed items={reflections ?? []} />
      </section>
    </div>
  );
}
