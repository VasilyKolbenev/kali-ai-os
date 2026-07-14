import { apiUrl, rustApiUrl } from "./runtime";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RustRoute {
  method: HttpMethod;
  path: string;
  /**
   * When true, `path` is treated as a prefix: any request whose
   * resolved path equals `path` or begins with `path + "/"` is
   * dispatched to Rust. Used for path-param routes such as
   * `/catalog/pack/{name}`. Default (omitted/false) is exact match.
   */
  prefix?: boolean;
}

/**
 * Method+path pairs served by the Rust backend on port 3006.
 * Each entry declares which HTTP method on which path is handled by
 * Rust. Everything else goes to Python on 3005. Rust may either serve
 * a route natively (GET /health, GET /config) or proxy to Python
 * (GET /voice/status, PATCH /config).
 *
 * Grows as endpoints migrate from Python.
 */
export const RUST_ENDPOINTS: readonly RustRoute[] = [
  { method: "GET", path: "/health" },
  { method: "GET", path: "/version" },
  { method: "GET", path: "/config" },
  { method: "PATCH", path: "/config" },
  { method: "GET", path: "/voice/status" },
  { method: "POST", path: "/voice/start" },
  { method: "POST", path: "/voice/stop" },
  { method: "GET", path: "/skills/installed" },
  { method: "POST", path: "/skills/install" },
  { method: "POST", path: "/skills/uninstall" },
  { method: "POST", path: "/skills/validate" },
  { method: "GET", path: "/skills/catalog/sources" },
  { method: "GET", path: "/skills/catalog" },
  { method: "POST", path: "/skills/catalog/refresh" },
  { method: "GET", path: "/catalog/search" },
  { method: "GET", path: "/catalog/trending" },
  { method: "POST", path: "/catalog/pack", prefix: true },
  { method: "POST", path: "/catalog/install" },
  { method: "GET", path: "/catalog/info" },
  // Mobile pairing (P1.1) — both loopback-only seams live on the Rust
  // control plane (:3006): the token and the desktop LAN IPv4 + bind state.
  { method: "GET", path: "/pairing/token" },
  { method: "GET", path: "/pairing/lan-ip" },
  // Auto-update — живёт целиком на Rust control-plane (:3006)
  { method: "GET", path: "/updater/status" },
  { method: "POST", path: "/updater/check" },
  { method: "POST", path: "/updater/download" },
  { method: "POST", path: "/updater/install" },
] as const;

function pathOf(input: string): string {
  const withSlash = input.startsWith("/") ? input : `/${input}`;
  const qIndex = withSlash.indexOf("?");
  const path = qIndex === -1 ? withSlash : withSlash.slice(0, qIndex);
  return path.endsWith("/") && path.length > 1 ? path.slice(0, -1) : path;
}

export function resolveApiUrl(path: string, method: HttpMethod = "GET"): string {
  const resolved = pathOf(path);
  const inRust = RUST_ENDPOINTS.some((e) => {
    if (e.method !== method) return false;
    if (e.prefix) {
      return resolved === e.path || resolved.startsWith(e.path + "/");
    }
    return e.path === resolved;
  });
  return inRust ? rustApiUrl(path) : apiUrl(path);
}
