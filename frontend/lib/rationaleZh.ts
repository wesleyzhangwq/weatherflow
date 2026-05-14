/** Normalize legacy English heuristic rationales for display. */
const LEGACY_HEURISTIC_EN =
  /Heuristic estimate\s*\(LLM unavailable\)\.?/gi;

export function displayRationaleZh(
  rationale: string | null | undefined
): string | null {
  if (rationale == null || !rationale.trim()) return null;
  const out = rationale.replace(LEGACY_HEURISTIC_EN, "离线启发式估计，仅供参考。");
  return out.trim() || null;
}
