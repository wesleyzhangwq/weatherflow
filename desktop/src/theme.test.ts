import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_STORAGE_KEY,
  applyThemePreference,
  getThemePreference,
  initializeTheme,
  setThemePreference,
} from "./theme";

function stubSystemTheme(dark: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = {
    matches: dark,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: vi.fn((_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener)),
    removeEventListener: vi.fn((_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener)),
    dispatchEvent: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  } as unknown as MediaQueryList;
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return { media, listeners };
}

describe("desktop theme preference", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size; },
    } satisfies Storage);
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.style.removeProperty("color-scheme");
  });

  it("defaults to the system theme and reacts to operating-system changes", () => {
    const { media, listeners } = stubSystemTheme(false);
    const stop = initializeTheme();

    expect(getThemePreference()).toBe("system");
    expect(document.documentElement.dataset.theme).toBe("light");

    Object.defineProperty(media, "matches", { configurable: true, value: true });
    listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent));
    expect(document.documentElement.dataset.theme).toBe("dark");
    stop();
  });

  it("persists an explicit light or dark preference under weatherflow.theme", () => {
    stubSystemTheme(true);
    setThemePreference("light");

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");

    setThemePreference("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("falls back safely when persisted data is invalid", () => {
    stubSystemTheme(true);
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");

    expect(getThemePreference()).toBe("system");
    expect(applyThemePreference(getThemePreference())).toBe("dark");
  });
});
