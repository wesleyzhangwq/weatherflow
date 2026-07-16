export interface BrowserTab {
  id: number;
  windowId: number;
  active: boolean;
  audible?: boolean;
  incognito: boolean;
  title?: string;
  url?: string;
}

export function browserCategory(domain: string): string;
export function browserTabToHeartbeat(
  tab: BrowserTab,
  context: {
    browserName: string;
    deviceId: string;
    eventId: string;
    observedAt: Date;
    focused?: boolean;
  },
): Record<string, unknown>;
