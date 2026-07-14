export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "weatherflow.theme";
const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function getThemePreference(): ThemePreference {
  let stored: string | null = null;
  try {
    stored = typeof window.localStorage?.getItem === "function"
      ? window.localStorage.getItem(THEME_STORAGE_KEY)
      : null;
  } catch { /* localStorage can be unavailable in hardened webviews */ }
  return isThemePreference(stored) ? stored : "system";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference !== "system") return preference;
  return window.matchMedia?.(SYSTEM_DARK_QUERY).matches ? "dark" : "light";
}

export function applyThemePreference(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  return resolved;
}

export function setThemePreference(preference: ThemePreference): ResolvedTheme {
  try {
    if (typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    }
  } catch { /* applying the theme still works for this window */ }
  const resolved = applyThemePreference(preference);
  window.dispatchEvent(new CustomEvent("weatherflow:theme", { detail: { preference, resolved } }));
  return resolved;
}

export function initializeTheme(): () => void {
  const media = window.matchMedia?.(SYSTEM_DARK_QUERY);
  const refresh = () => applyThemePreference(getThemePreference());
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) refresh();
  };
  const onTheme = () => refresh();

  refresh();
  media?.addEventListener("change", refresh);
  window.addEventListener("storage", onStorage);
  window.addEventListener("weatherflow:theme", onTheme);

  return () => {
    media?.removeEventListener("change", refresh);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("weatherflow:theme", onTheme);
  };
}
