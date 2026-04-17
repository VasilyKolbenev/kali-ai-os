declare global {
  interface Window {
    __KALI_CONFIG__?: {
      apiBaseUrl?: string;
      wsUrl?: string;
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

export const wsUrl =
  env.VITE_KALI_WS_URL ||
  runtimeConfig?.wsUrl ||
  `${httpToWebSocket(apiBaseUrl)}/ws`;

export function apiUrl(path: string): string {
  return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
