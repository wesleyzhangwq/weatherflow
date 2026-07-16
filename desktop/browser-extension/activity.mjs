const DEVELOPMENT_DOMAINS = new Set([
  "github.com",
  "gitlab.com",
  "stackoverflow.com",
  "developer.mozilla.org",
]);
const COMMUNICATION_DOMAINS = new Set([
  "mail.google.com",
  "outlook.office.com",
  "slack.com",
  "discord.com",
]);
const PLANNING_DOMAINS = new Set([
  "calendar.google.com",
  "docs.google.com",
  "notion.so",
  "linear.app",
]);

export function browserCategory(domain) {
  if (DEVELOPMENT_DOMAINS.has(domain)) return "development";
  if (COMMUNICATION_DOMAINS.has(domain)) return "communication";
  if (PLANNING_DOMAINS.has(domain)) return "planning";
  return "research";
}

export function browserTabToHeartbeat(tab, context) {
  if (tab.id == null || tab.windowId == null || !tab.url || !tab.title) {
    throw new Error("complete focused tab metadata is required");
  }
  const parsed = new URL(tab.url);
  return {
    source: "browser_tab",
    device_id: context.deviceId,
    source_instance: `weatherflow-browser-${context.browserName.toLowerCase().replaceAll(" ", "-")}`,
    source_event_id: context.eventId,
    observed_at: context.observedAt.toISOString(),
    pulsetime_seconds: 80,
    browser_name: context.browserName,
    browser_window_id: String(tab.windowId),
    browser_tab_id: String(tab.id),
    url: tab.url,
    domain: parsed.hostname,
    tab_title: tab.title,
    audible: Boolean(tab.audible),
    incognito: Boolean(tab.incognito),
    focused: context.focused ?? Boolean(tab.active),
    idle_state: context.idleState ?? "active",
    category: browserCategory(parsed.hostname),
  };
}
