import { apiUrl, rustApiUrl } from "./runtime";

/**
 * Paths served by the Rust backend on port 3006.
 * Grows as endpoints migrate from Python. Everything else goes to 3005.
 */
export const RUST_ENDPOINTS: readonly string[] = [
  "/health",
  "/version",
  "/config",
  "/voice/status",
] as const;

function pathOf(input: string): string {
  const withSlash = input.startsWith("/") ? input : `/${input}`;
  const qIndex = withSlash.indexOf("?");
  const path = qIndex === -1 ? withSlash : withSlash.slice(0, qIndex);
  return path.endsWith("/") && path.length > 1 ? path.slice(0, -1) : path;
}

export function resolveApiUrl(path: string): string {
  return RUST_ENDPOINTS.includes(pathOf(path)) ? rustApiUrl(path) : apiUrl(path);
}
