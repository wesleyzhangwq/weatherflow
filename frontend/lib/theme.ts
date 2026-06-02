export const THEME_STORAGE_KEY = "weatherflow.theme";

export type ThemeMode = "system" | "day" | "night";
export type ResolvedTheme = "day" | "night";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

type RootLike = {
  classList: Pick<DOMTokenList, "add" | "remove">;
  style: Pick<CSSStyleDeclaration, "colorScheme">;
};

export function isThemeMode(value: string | null): value is ThemeMode {
  return value === "system" || value === "day" || value === "night";
}

export function getStoredThemeMode(storage: StorageLike): ThemeMode {
  const stored = storage.getItem(THEME_STORAGE_KEY);
  if (stored === "day" || stored === "night") return stored;
  return "system";
}

export function setStoredThemeMode(storage: StorageLike, mode: ThemeMode) {
  if (mode === "system") {
    storage.removeItem(THEME_STORAGE_KEY);
    return;
  }
  storage.setItem(THEME_STORAGE_KEY, mode);
}

export function resolveThemeMode(
  mode: ThemeMode,
  systemPrefersDark: boolean
): ResolvedTheme {
  if (mode === "day") return "day";
  if (mode === "night") return "night";
  return systemPrefersDark ? "night" : "day";
}

export function applyResolvedTheme(root: RootLike, resolved: ResolvedTheme) {
  if (resolved === "night") {
    root.classList.add("dark");
    root.style.colorScheme = "dark";
    return;
  }

  root.classList.remove("dark");
  root.style.colorScheme = "light";
}
