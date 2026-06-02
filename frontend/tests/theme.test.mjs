import assert from "node:assert/strict";
import test from "node:test";

import {
  applyResolvedTheme,
  getStoredThemeMode,
  resolveThemeMode,
  setStoredThemeMode,
  THEME_STORAGE_KEY
} from "../lib/theme.ts";

function makeRoot() {
  const classes = new Set();
  return {
    classList: {
      add(value) {
        classes.add(value);
      },
      remove(value) {
        classes.delete(value);
      },
      contains(value) {
        return classes.has(value);
      }
    },
    style: {
      colorScheme: ""
    }
  };
}

function makeStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    }
  };
}

test("resolves the three theme modes", () => {
  assert.equal(resolveThemeMode("day", true), "day");
  assert.equal(resolveThemeMode("night", false), "night");
  assert.equal(resolveThemeMode("system", true), "night");
  assert.equal(resolveThemeMode("system", false), "day");
});

test("applies day and night to the root element", () => {
  const root = makeRoot();

  applyResolvedTheme(root, "night");
  assert.equal(root.classList.contains("dark"), true);
  assert.equal(root.style.colorScheme, "dark");

  applyResolvedTheme(root, "day");
  assert.equal(root.classList.contains("dark"), false);
  assert.equal(root.style.colorScheme, "light");
});

test("stores explicit modes and clears system mode", () => {
  const storage = makeStorage();

  setStoredThemeMode(storage, "night");
  assert.equal(storage.getItem(THEME_STORAGE_KEY), "night");
  assert.equal(getStoredThemeMode(storage), "night");

  setStoredThemeMode(storage, "system");
  assert.equal(storage.getItem(THEME_STORAGE_KEY), null);
  assert.equal(getStoredThemeMode(storage), "system");
});

test("ignores unknown stored values", () => {
  const storage = makeStorage({ [THEME_STORAGE_KEY]: "sepia" });

  assert.equal(getStoredThemeMode(storage), "system");
});
