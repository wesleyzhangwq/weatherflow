import { browserTabToHeartbeat } from "./activity.mjs";

const api = globalThis.browser ?? globalThis.chrome;
const SETTINGS_KEY = "weatherflowActivitySettings";
const STATUS_KEY = "weatherflowActivityStatus";
const DEFAULTS = {
  enabled: false,
  includeIncognito: false,
  baseUrl: "http://127.0.0.1:8765",
  bridgeToken: "",
  deviceId: "",
};
let sampleQueue = Promise.resolve();

function browserName() {
  const agent = globalThis.navigator.userAgent;
  if (agent.includes("Firefox")) return "Firefox";
  if (agent.includes("Edg/")) return "Edge";
  if (agent.includes("Chrome")) return "Chrome";
  return "Browser";
}

async function settings() {
  const stored = (await api.storage.local.get(SETTINGS_KEY))[SETTINGS_KEY] ?? {};
  const merged = { ...DEFAULTS, ...stored };
  if (!merged.deviceId) {
    merged.deviceId = globalThis.crypto.randomUUID();
    await api.storage.local.set({ [SETTINGS_KEY]: merged });
  }
  return merged;
}

async function setStatus(state, detail = null) {
  await api.storage.local.set({
    [STATUS_KEY]: {
      state,
      detail,
      checkedAt: new Date().toISOString(),
    },
  });
}

function headers(configuration) {
  const result = { "Content-Type": "application/json" };
  if (configuration.bridgeToken) {
    result.Authorization = `Bearer ${configuration.bridgeToken}`;
  }
  return result;
}

async function weatherFlowPreferences(configuration) {
  const response = await fetch(`${configuration.baseUrl}/v1/activity/preferences`, {
    headers: headers(configuration),
  });
  if (!response.ok) throw new Error(`bridge_${response.status}`);
  return response.json();
}

async function idleState() {
  const state = await api.idle.queryState(60);
  return state === "idle" || state === "locked" ? "idle" : "active";
}

async function sampleFocusedTab() {
  const configuration = await settings();
  if (!configuration.enabled) {
    await setStatus("paused");
    return;
  }
  const preferences = await weatherFlowPreferences(configuration);
  if (!preferences.collection_enabled || !preferences.browser_enabled) {
    await setStatus("needs_weatherflow_opt_in");
    return;
  }
  const focusedWindow = await api.windows.getLastFocused({ populate: true });
  const tab = focusedWindow.tabs?.find((candidate) => candidate.active);
  if (!tab?.url || !tab?.title || tab.id == null) {
    await setStatus("unsupported_tab");
    return;
  }
  if (tab.incognito && (!configuration.includeIncognito || !preferences.incognito_enabled)) {
    await setStatus("incognito_paused");
    return;
  }
  const heartbeat = browserTabToHeartbeat(tab, {
    browserName: browserName(),
    deviceId: configuration.deviceId,
    eventId: globalThis.crypto.randomUUID(),
    observedAt: new Date(),
    idleState: await idleState(),
    focused: Boolean(focusedWindow.focused && tab.active),
  });
  const response = await fetch(`${configuration.baseUrl}/v1/activity/heartbeats`, {
    method: "POST",
    headers: headers(configuration),
    body: JSON.stringify(heartbeat),
  });
  if (!response.ok) throw new Error(`bridge_${response.status}`);
  await setStatus("connected", heartbeat.domain);
}

function safeSample() {
  sampleQueue = sampleQueue
    .catch(() => undefined)
    .then(() => sampleFocusedTab())
    .catch((error) => setStatus(
      "error",
      error instanceof Error ? error.message : "unknown_error",
    ));
  return sampleQueue;
}

api.runtime.onInstalled.addListener(() => {
  void api.alarms.create("weatherflow-activity-heartbeat", { periodInMinutes: 1 });
  void setStatus("paused");
});
api.runtime.onStartup.addListener(() => {
  void api.alarms.create("weatherflow-activity-heartbeat", { periodInMinutes: 1 });
  void safeSample();
});
api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "weatherflow-activity-heartbeat") void safeSample();
});
api.tabs.onActivated.addListener(() => { void safeSample(); });
api.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url || changeInfo.title || changeInfo.audible != null) {
    void safeSample();
  }
});
api.windows.onFocusChanged.addListener(() => { void safeSample(); });
api.runtime.onMessage.addListener((message) => {
  if (message?.type === "weatherflow.activity.sample") return safeSample();
  return undefined;
});
