/**
 * Build the `kali://pair` deep-link the desktop encodes into the pairing QR.
 *
 * The phone's native camera opens this link in KALI; the mobile deep-link
 * handler (Task 2) extracts `ip` + `token` and connects. The mobile side
 * appends the `:3006` port itself (`ServerConfig.port`), so the `ip` param
 * here is the BARE LAN IPv4 — no port — and the token is URL-encoded.
 *
 * @param ip - Desktop LAN IPv4 (bare host, no port).
 * @param token - Per-install control-plane token (raw; encoded here).
 * @returns The `kali://pair?ip=<ip>&token=<token>` deep link.
 */
export function buildPairLink(ip: string, token: string): string {
  const params = new URLSearchParams({ ip, token });
  return `kali://pair?${params.toString()}`;
}
