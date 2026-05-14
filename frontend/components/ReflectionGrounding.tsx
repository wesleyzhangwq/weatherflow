import type { GroundingSource } from "@/lib/api";

export function ReflectionGrounding({
  sources
}: {
  sources?: GroundingSource[];
}) {
  const visible = (sources ?? [])
    .filter((source) => source.label && source.summary)
    .slice(0, 6);

  if (visible.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl border border-black/10 dark:border-white/10 px-3 py-2">
      <div className="text-xs uppercase tracking-widest muted">
        这次反思参考了
      </div>
      <ul className="mt-2 space-y-1.5 text-sm">
        {visible.map((source) => (
          <li key={`${source.type}-${source.label}`}>
            <span className="font-medium">{source.label}</span>
            <span className="muted">：{trimSummary(source.summary)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function trimSummary(summary: string) {
  return summary.length > 120 ? `${summary.slice(0, 120)}...` : summary;
}
