"use client";

export function MomentumGauge({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value));
  const radius = 56;
  const circ = 2 * Math.PI * radius;
  const offset = circ * (1 - v / 100);
  return (
    <div className="card flex flex-col items-center">
      <div className="text-xs uppercase tracking-widest muted self-start">动能</div>
      <svg width="140" height="140" viewBox="0 0 140 140" className="mt-2">
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.1"
          strokeWidth="10"
        />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          transform="rotate(-90 70 70)"
        />
        <text
          x="70"
          y="78"
          textAnchor="middle"
          fontSize="28"
          fontFamily="ui-serif, Georgia, serif"
          fill="currentColor"
        >
          {v}
        </text>
      </svg>
      <div className="muted text-xs mt-2">0 — 100</div>
    </div>
  );
}
