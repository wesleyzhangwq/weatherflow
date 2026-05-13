"use client";

export function BurnoutIndicator({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value));
  const tone =
    v < 30 ? "calm" : v < 60 ? "watch" : "high";
  const label =
    v < 30 ? "低" : v < 60 ? "留意" : "偏高";
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-widest muted">倦怠风险</div>
      <div className="mt-3 font-serif text-3xl">{label}</div>
      <div className="mt-3 h-2 rounded-full bg-black/5 dark:bg-white/10 overflow-hidden">
        <div
          className="h-full"
          style={{
            width: `${v}%`,
            background:
              tone === "high"
                ? "rgba(220,80,80,0.8)"
                : tone === "watch"
                ? "rgba(220,170,80,0.8)"
                : "rgba(110,160,140,0.8)"
          }}
        />
      </div>
      <div className="muted text-xs mt-2">{v} / 100</div>
    </div>
  );
}
