export type Surface = "companion" | "capsule" | "cockpit";

export function surfaceFromLocation(search: string): Surface {
  const value = new URLSearchParams(search).get("surface");
  return value === "capsule" || value === "cockpit" ? value : "companion";
}
