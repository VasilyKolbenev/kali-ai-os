declare global {
  interface Window {
    __KALI_CONFIG__?: {
      apiBaseUrl?: string;
      rustApiBaseUrl?: string;
      wsUrl?: string;
      rustWsUrl?: string;
    };
  }
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function httpToWebSocket(url: string): string {
  if (url.startsWith("https://")) {
    return `wss://${url.slice("https://".length)}`;
  }
  if (url.startsWith("http://")) {
    return `ws://${url.slice("http://".length)}`;
  }
  return url;
}

const runtimeConfig = window.__KALI_CONFIG__;
const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env ?? {};

export const apiBaseUrl = trimTrailingSlash(
  env.VITE_KALI_API_BASE_URL ||
    runtimeConfig?.apiBaseUrl ||
    "http://127.0.0.1:3005",
);

export const rustApiBaseUrl = trimTrailingSlash(
  env.VITE_KALI_RUST_API_BASE_URL ||
    runtimeConfig?.rustApiBaseUrl ||
    apiBaseUrl.replace(/:3005$/, ":3006") ||
    "http://127.0.0.1:3006",
);

/**
 * Legacy WebSocket URL (Python backend on :3005). Kept as a named export so
 * runtime overrides can flip back in the field if Phase 2 needs to be
 * rolled back without reinstalling — set
 * `window.__KALI_CONFIG__.rustWsUrl = wsUrl` in the Tauri bootstrap.
 */
export const wsUrl =
  env.VITE_KALI_WS_URL ||
  runtimeConfig?.wsUrl ||
  `${httpToWebSocket(apiBaseUrl)}/ws`;

/**
 * Primary WebSocket URL after Phase 2 — points at the Rust backend on
 * :3006. Python's /ws stays alive until Phase 8 as a rollback path.
 */
export const rustWsUrl =
  env.VITE_KALI_RUST_WS_URL ||
  runtimeConfig?.rustWsUrl ||
  `${httpToWebSocket(rustApiBaseUrl)}/ws`;

export function apiUrl(path: string): string {
  return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export function rustApiUrl(path: string): string {
  return `${rustApiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
