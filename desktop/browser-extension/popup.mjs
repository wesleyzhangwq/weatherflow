const api = globalThis.browser ?? globalThis.chrome;
const SETTINGS_KEY = "weatherflowActivitySettings";
const STATUS_KEY = "weatherflowActivityStatus";

const enabled = document.querySelector("#enabled");
const incognito = document.querySelector("#incognito");
const baseUrl = document.querySelector("#base-url");
const bridgeToken = document.querySelector("#bridge-token");
const status = document.querySelector("#status");
const dot = document.querySelector("#status-dot");

const statusText = {
  connected: "已连接，正在记录当前标签页",
  paused: "已暂停",
  needs_weatherflow_opt_in: "请先在 WeatherFlow 中开启浏览器活动授权",
  incognito_paused: "无痕活动未获双重授权",
  unsupported_tab: "此浏览器内部页面不可记录",
  error: "无法连接 WeatherFlow 本机服务",
};

async function render() {
  const stored = await api.storage.local.get([SETTINGS_KEY, STATUS_KEY]);
  const settings = stored[SETTINGS_KEY] ?? {};
  const current = stored[STATUS_KEY] ?? { state: "paused" };
  enabled.checked = Boolean(settings.enabled);
  incognito.checked = Boolean(settings.includeIncognito);
  baseUrl.value = settings.baseUrl ?? "http://127.0.0.1:8765";
  bridgeToken.value = settings.bridgeToken ?? "";
  status.textContent = statusText[current.state] ?? "等待连接";
  dot.dataset.state = current.state;
}

document.querySelector("#save").addEventListener("click", async () => {
  const existing = (await api.storage.local.get(SETTINGS_KEY))[SETTINGS_KEY] ?? {};
  await api.storage.local.set({
    [SETTINGS_KEY]: {
      ...existing,
      enabled: enabled.checked,
      includeIncognito: incognito.checked,
      baseUrl: baseUrl.value.replace(/\/$/, ""),
      bridgeToken: bridgeToken.value,
    },
  });
  await api.runtime.sendMessage({ type: "weatherflow.activity.sample" });
  await render();
});
document.querySelector("#sample").addEventListener("click", async () => {
  await api.runtime.sendMessage({ type: "weatherflow.activity.sample" });
  await render();
});
api.storage.onChanged.addListener(() => { void render(); });
void render();
