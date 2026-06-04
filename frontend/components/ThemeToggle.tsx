"use client";

import { useEffect, useMemo, useState } from "react";
import {
  applyResolvedTheme,
  getStoredThemeMode,
  resolveThemeMode,
  setStoredThemeMode,
  type ThemeMode
} from "@/lib/theme";

const OPTIONS: Array<{ mode: ThemeMode; label: string }> = [
  { mode: "system", label: "跟随系统" },
  { mode: "day", label: "白天" },
  { mode: "night", label: "黑夜" }
];

function getSystemMatcher() {
  if (typeof window === "undefined") return null;
  return window.matchMedia("(prefers-color-scheme: dark)");
}

export function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("system");
  const [systemPrefersDark, setSystemPrefersDark] = useState(false);

  useEffect(() => {
    const matcher = getSystemMatcher();
    const stored = getStoredThemeMode(window.localStorage);

    setMode(stored);
    setSystemPrefersDark(Boolean(matcher?.matches));
    applyResolvedTheme(
      document.documentElement,
      resolveThemeMode(stored, Boolean(matcher?.matches))
    );

    if (!matcher) return;

    const onChange = (event: MediaQueryListEvent) => {
      setSystemPrefersDark(event.matches);
      const current = getStoredThemeMode(window.localStorage);
      applyResolvedTheme(
        document.documentElement,
        resolveThemeMode(current, event.matches)
      );
    };

    matcher.addEventListener("change", onChange);
    return () => matcher.removeEventListener("change", onChange);
  }, []);

  const resolved = useMemo(
    () => resolveThemeMode(mode, systemPrefersDark),
    [mode, systemPrefersDark]
  );

  function choose(nextMode: ThemeMode) {
    setMode(nextMode);
    setStoredThemeMode(window.localStorage, nextMode);
    applyResolvedTheme(
      document.documentElement,
      resolveThemeMode(nextMode, systemPrefersDark)
    );
  }

  return (
    <div
      aria-label={`主题：${mode === "system" ? "跟随系统" : mode === "day" ? "白天" : "黑夜"}，当前为${resolved === "night" ? "黑夜" : "白天"}`}
      className="flex rounded-lg border border-black/10 bg-black/[0.03] p-0.5 text-xs dark:border-white/15 dark:bg-white/[0.06]"
      role="group"
    >
      {OPTIONS.map((option) => {
        const active = option.mode === mode;
        return (
          <button
            key={option.mode}
            aria-pressed={active}
            className={`min-h-8 rounded-md px-2.5 transition ${
              active
                ? "bg-white text-black shadow-sm dark:bg-white/90 dark:text-black"
                : "text-black/60 hover:text-black dark:text-white/60 dark:hover:text-white"
            }`}
            type="button"
            onClick={() => choose(option.mode)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
