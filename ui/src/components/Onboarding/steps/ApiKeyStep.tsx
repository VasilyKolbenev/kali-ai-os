import { useState } from "react";
import { PROVIDERS } from "../providers";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { api } from "../../../api/client";
import { HexFrame } from "../../hud";
import { FadeSlideUp } from "../../../motion";

type CheckStatus = "idle" | "checking" | "valid" | "invalid";

export function ApiKeyStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const setProvider = useOnboardingStore((s) => s.setApiProvider);
  const setValid = useOnboardingStore((s) => s.setApiKeyValid);
  const selected = useOnboardingStore((s) => s.apiProvider);

  const [key, setKey] = useState("");
  const [status, setStatus] = useState<CheckStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const meta = PROVIDERS.find((p) => p.id === selected);

  async function handleCheck() {
    if (!selected || !key) return;
    setStatus("checking");
    setError(null);
    try {
      const res = await api.testApiKey(selected, key);
      if (res.ok) {
        setStatus("valid");
        setValid(true);
        await api.updateSettings({ [`api_key_${selected}`]: key });
        setTimeout(() => advance(), 600);
      } else {
        setStatus("invalid");
        setError(res.error ?? "Ключ не подошёл. Проверь ещё раз.");
      }
    } catch (e) {
      setStatus("invalid");
      setError(e instanceof Error ? e.message : "unknown error");
    }
  }

  function handleSkip() {
    setValid(false);
    advance();
  }

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-2xl w-full">
        <h2
          style={{
            fontSize: "var(--j-text-xl)",
            color: "var(--j-text)",
            textAlign: "center",
          }}
        >
          Чтобы я думал, дай ключ от мозга
        </h2>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: "var(--j-space-3)",
            width: "100%",
          }}
        >
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                setProvider(p.id);
                setStatus("idle");
                setError(null);
              }}
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
            >
              <HexFrame active={selected === p.id}>
                <div
                  style={{
                    padding: "var(--j-space-4)",
                    textAlign: "center",
                    color: "var(--j-text)",
                    fontFamily: "var(--j-font-mono)",
                    letterSpacing: "var(--j-tracking-wide)",
                  }}
                >
                  {p.label}
                </div>
              </HexFrame>
            </button>
          ))}
        </div>

        {meta && (
          <div className="flex flex-col items-center gap-3 w-full">
            <a
              href={meta.helpUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: "var(--j-text-xs)",
                color: "var(--j-cyan-dim)",
                letterSpacing: "var(--j-tracking-wide)",
              }}
            >
              Где взять ключ {meta.label} →
            </a>
            <input
              type="password"
              placeholder={meta.placeholder}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              style={{
                width: "100%",
                maxWidth: "420px",
                padding: "var(--j-space-3) var(--j-space-4)",
                background: "var(--j-surface)",
                border: `1px solid ${
                  status === "invalid" ? "var(--j-danger)" : "var(--j-border)"
                }`,
                borderRadius: "var(--j-radius-md)",
                color: "var(--j-text)",
                fontFamily: "var(--j-font-mono)",
              }}
            />
            <button
              onClick={handleCheck}
              disabled={!key || status === "checking"}
              style={{
                padding: "var(--j-space-3) var(--j-space-6)",
                background:
                  status === "valid"
                    ? "color-mix(in srgb, var(--j-success) 20%, transparent)"
                    : "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
                border: `1px solid ${
                  status === "valid" ? "var(--j-success)" : "var(--j-border-glow)"
                }`,
                borderRadius: "var(--j-radius-md)",
                color: status === "valid" ? "var(--j-success)" : "var(--j-cyan)",
                fontFamily: "var(--j-font-mono)",
                letterSpacing: "var(--j-tracking-wide)",
                textTransform: "uppercase",
                cursor: "pointer",
                fontSize: "var(--j-text-sm)",
              }}
            >
              {status === "checking"
                ? "Проверяю..."
                : status === "valid"
                  ? "✓ Ключ работает"
                  : "Проверить"}
            </button>
            {error && (
              <div style={{ color: "var(--j-danger)", fontSize: "var(--j-text-sm)" }}>
                {error}
              </div>
            )}
          </div>
        )}

        <button
          onClick={handleSkip}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--j-text-muted)",
            cursor: "pointer",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
          }}
        >
          У меня нет ключа — пропустить
        </button>
      </div>
    </FadeSlideUp>
  );
}
