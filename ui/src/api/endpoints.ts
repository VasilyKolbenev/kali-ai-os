import { apiUrl, rustApiUrl } from "./runtime";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RustRoute {
  method: HttpMethod;
  path: string;
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
] as const;

function pathOf(input: string): string {
  const withSlash = input.startsWith("/") ? input : `/${input}`;
  const qIndex = withSlash.indexOf("?");
  const path = qIndex === -1 ? withSlash : withSlash.slice(0, qIndex);
  return path.endsWith("/") && path.length > 1 ? path.slice(0, -1) : path;
}

export function resolveApiUrl(path: string, method: HttpMethod = "GET"): string {
  const resolved = pathOf(path);
  const inRust = RUST_ENDPOINTS.some(
    (e) => e.method === method && e.path === resolved,
  );
  return inRust ? rustApiUrl(path) : apiUrl(path);
}
