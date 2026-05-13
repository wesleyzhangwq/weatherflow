import { GrowthTimeline } from "@/components/GrowthTimeline";
import { API_BASE, type TimelineEvent } from "@/lib/api";

async function fetchTimeline(): Promise<TimelineEvent[]> {
  try {
    const r = await fetch(`${API_BASE}/api/timeline?limit=200`, { cache: "no-store" });
    if (!r.ok) return [];
    return (await r.json()) as TimelineEvent[];
  } catch {
    return [];
  }
}

export default async function TimelinePage() {
  const items = await fetchTimeline();
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-serif text-4xl">成长时间线</h1>
        <p className="muted mt-1">
          长期旅程的轮廓。你持续出现时，它会自己慢慢长出来。
        </p>
      </header>
      <GrowthTimeline items={items} />
    </div>
  );
}
