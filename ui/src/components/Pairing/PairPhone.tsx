import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Smartphone, AlertTriangle } from "lucide-react";
import { api } from "../../api/client";
import { HexFrame, HudDivider } from "../hud";
import { buildPairLink } from "./pairLink";

/** Resolved pairing state once token + LAN IP have been fetched. */
interface PairState {
  token: string;
  ip: string | null;
  lanEnabled: boolean;
}

/**
 * "Подключить телефон" — renders the `kali://pair` QR a phone scans with its
 * native camera to join the desktop as a tethered companion over LAN.
 *
 * Fetches the per-install token + LAN IPv4 from the loopback-only Rust seams
 * (`/pairing/token`, `/pairing/lan-ip`). The backend LAN-binds only at startup
 * (`KALI_LAN=1`) — there is no runtime rebind — so when LAN is off this view
 * shows an honest "enable LAN and restart" prompt instead of an unreachable QR.
 */
export function PairPhone() {
  const [state, setState] = useState<PairState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.pairingToken(), api.pairingLanIp()])
      .then(([t, lan]) =>
        setState({ token: t.token, ip: lan.ip, lanEnabled: lan.lan_enabled }),
      )
      .catch((e) =>
        setError(
          `Не удалось получить данные для подключения: ${
            e instanceof Error ? e.message : e
          }`,
        ),
      );
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", padding: "var(--j-space-6)", overflow: "auto" }}>
      <div style={{ maxWidth: "42rem", margin: "0 auto" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--j-space-3)",
            marginBottom: "var(--j-space-5)",
          }}
        >
          <Smartphone style={{ width: 18, height: 18, color: "var(--j-cyan)" }} />
          <h2
            style={{
              fontFamily: "var(--j-font-mono)",
              fontSize: "var(--j-text-lg)",
              letterSpacing: "var(--j-tracking-hud)",
              textTransform: "uppercase",
              color: "var(--j-text)",
            }}
          >
            Подключить телефон
          </h2>
        </div>

        {error && <div style={{ color: "var(--j-danger)" }}>{error}</div>}

        {!error && !state && (
          <div style={{ color: "var(--j-text-muted)" }}>Готовлю код подключения…</div>
        )}

        {!error && state && <PairBody state={state} />}
      </div>
    </div>
  );
}

/** The resolved body: either the LAN-off prompt or the QR + instructions. */
function PairBody({ state }: { state: PairState }) {
  const reachable = state.lanEnabled && Boolean(state.ip);

  if (!reachable) {
    return <LanDisabledNotice hasIp={Boolean(state.ip)} />;
  }

  const link = buildPairLink(state.ip as string, state.token);
  return (
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="QR-КОД" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div
          style={{
            padding: "var(--j-space-5)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "var(--j-space-4)",
          }}
        >
          <div style={{ background: "#fff", padding: "var(--j-space-3)", borderRadius: "var(--j-radius-md)" }}>
            <QRCodeSVG value={link} size={208} level="M" />
          </div>
          <p
            style={{
              textAlign: "center",
              maxWidth: "22rem",
              color: "var(--j-text-dim)",
              fontSize: "var(--j-text-sm)",
            }}
          >
            Наведите камеру телефона на QR-код, чтобы подключить KALI. Телефон и
            этот компьютер должны быть в одной сети Wi-Fi.
          </p>
          <code
            style={{
              userSelect: "all",
              wordBreak: "break-all",
              textAlign: "center",
              fontFamily: "var(--j-font-mono)",
              fontSize: "var(--j-text-xs)",
              color: "var(--j-text-muted)",
            }}
          >
            {link}
          </code>
        </div>
      </HexFrame>
    </div>
  );
}

/**
 * Shown when the backend is NOT LAN-bound (or no LAN IPv4 was found). The bind
 * is fixed at startup, so the only honest path is: set `KALI_LAN=1` and restart.
 */
function LanDisabledNotice({ hasIp }: { hasIp: boolean }) {
  return (
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="ДОСТУП ПО СЕТИ ВЫКЛЮЧЕН" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div
          style={{
            padding: "var(--j-space-4)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--j-space-3)",
            fontSize: "var(--j-text-sm)",
            color: "var(--j-text-dim)",
          }}
        >
          <div style={{ display: "flex", gap: "var(--j-space-2)", alignItems: "flex-start" }}>
            <AlertTriangle
              style={{ width: 16, height: 16, color: "var(--j-amber, #f59e0b)", flexShrink: 0, marginTop: 2 }}
            />
            <span>
              {hasIp
                ? "Чтобы телефон смог подключиться, KALI должен принимать соединения по локальной сети."
                : "Не найден сетевой адрес этого компьютера. Проверьте, что вы подключены к Wi-Fi, и включите доступ по сети."}
            </span>
          </div>
          <ol
            style={{
              margin: 0,
              paddingLeft: "var(--j-space-5)",
              display: "flex",
              flexDirection: "column",
              gap: "var(--j-space-2)",
            }}
          >
            <li>
              Запустите KALI с переменной окружения{" "}
              <code style={{ fontFamily: "var(--j-font-mono)", color: "var(--j-cyan)" }}>KALI_LAN=1</code>.
            </li>
            <li>Перезапустите приложение и снова откройте этот экран — появится QR-код.</li>
          </ol>
        </div>
      </HexFrame>
    </div>
  );
}
