import { useEffect, useState } from "react";
import { api } from "../../../api/client";
import { HexFrame, HudDivider } from "../../hud";

export interface VoiceSettingsValue {
  wake_word: string;
  mode: string;
  auto_start: boolean;
}

const MODES: { id: string; label: string; hint: string }[] = [
  { id: "wake_word", label: "ПО СЛОВУ", hint: "Ждёт wake word в фоне" },
  { id: "push_to_talk", label: "КНОПКА", hint: "Запись по запросу" },
  { id: "off", label: "ВЫКЛ", hint: "Голос отключён" },
];

const fieldLabelStyle = {
  display: "block",
  marginBottom: "var(--j-space-1)",
  fontSize: "var(--j-text-xs)",
  color: "var(--j-text-dim)",
  fontFamily: "var(--j-font-mono)",
  letterSpacing: "var(--j-tracking-wide)",
  textTransform: "uppercase" as const,
};

const inputStyle = {
  width: "100%",
  padding: "var(--j-space-2) var(--j-space-3)",
  background: "var(--j-surface)",
  border: "1px solid var(--j-border)",
  borderRadius: "var(--j-radius-md)",
  color: "var(--j-text)",
  fontFamily: "var(--j-font-mono)",
  fontSize: "var(--j-text-sm)",
};

export function VoiceSettings() {
  const [initial, setInitial] = useState<VoiceSettingsValue | null>(null);
  const [draft, setDraft] = useState<VoiceSettingsValue | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<
    { tone: "success" | "error" | "hint"; text: string } | null
  >(null);

  useEffect(() => {
    api
      .config()
      .then((cfg) => {
        const voice = (cfg.voice ?? {}) as Partial<VoiceSettingsValue>;
        const resolved: VoiceSettingsValue = {
          wake_word: voice.wake_word ?? "jarvis",
          mode: voice.mode ?? "wake_word",
          auto_start: voice.auto_start ?? false,
        };
        setInitial(resolved);
        setDraft(resolved);
      })
      .catch((err) =>
        setMessage({
          tone: "error",
          text: `Не удалось прочитать config: ${
            err instanceof Error ? err.message : String(err)
          }`,
        }),
      );
  }, []);

  const dirty =
    !!initial &&
    !!draft &&
    (initial.wake_word !== draft.wake_word ||
      initial.mode !== draft.mode ||
      initial.auto_start !== draft.auto_start);

  async function save() {
    if (!draft || !dirty) return;
    setSaving(true);
    setMessage(null);
    try {
      const trimmed = draft.wake_word.trim();
      if (!trimmed) throw new Error("wake_word не может быть пустым");
      const patch = {
        voice: {
          wake_word: trimmed,
          mode: draft.mode,
          auto_start: draft.auto_start,
        },
      };
      await api.updateConfig(patch);
      const persisted: VoiceSettingsValue = { ...draft, wake_word: trimmed };
      setInitial(persisted);
      setDraft(persisted);
      setMessage({
        tone: "hint",
        text: "Сохранено. Изменения применятся при следующем запуске.",
      });
    } catch (err) {
      setMessage({
        tone: "error",
        text: `Ошибка: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
    setSaving(false);
  }

  return (
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="ГОЛОС" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div
          style={{
            padding: "var(--j-space-4)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--j-space-4)",
          }}
        >
          {draft ? (
            <>
              <div>
                <label style={fieldLabelStyle}>Wake word</label>
                <input
                  type="text"
                  value={draft.wake_word}
                  onChange={(e) =>
                    setDraft({ ...draft, wake_word: e.target.value })
                  }
                  placeholder="jarvis"
                  style={inputStyle}
                  aria-label="Wake word"
                />
              </div>

              <div>
                <label style={fieldLabelStyle}>Режим</label>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fit, minmax(140px, 1fr))",
                    gap: "var(--j-space-2)",
                  }}
                >
                  {MODES.map((m) => {
                    const selected = draft.mode === m.id;
                    return (
                      <button
                        key={m.id}
                        onClick={() => setDraft({ ...draft, mode: m.id })}
                        aria-pressed={selected}
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        <HexFrame active={selected}>
                          <div
                            style={{
                              padding: "var(--j-space-3)",
                              color: selected
                                ? "var(--j-cyan)"
                                : "var(--j-text-dim)",
                              fontFamily: "var(--j-font-mono)",
                              fontSize: "var(--j-text-xs)",
                              letterSpacing: "var(--j-tracking-wide)",
                              display: "flex",
                              flexDirection: "column",
                              gap: "var(--j-space-1)",
                            }}
                          >
                            <span style={{ textTransform: "uppercase" }}>
                              {m.label}
                            </span>
                            <span
                              style={{
                                color: "var(--j-text-muted)",
                                textTransform: "none",
                                letterSpacing: 0,
                              }}
                            >
                              {m.hint}
                            </span>
                          </div>
                        </HexFrame>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "var(--j-space-3)",
                }}
              >
                <div>
                  <span style={fieldLabelStyle}>Автостарт</span>
                  <span
                    style={{
                      display: "block",
                      fontSize: "var(--j-text-xs)",
                      color: "var(--j-text-muted)",
                    }}
                  >
                    Голосовой pipeline запустится вместе с приложением
                  </span>
                </div>
                <button
                  role="switch"
                  aria-checked={draft.auto_start}
                  aria-label="Автостарт голосового pipeline"
                  onClick={() =>
                    setDraft({ ...draft, auto_start: !draft.auto_start })
                  }
                  style={{
                    width: 48,
                    height: 26,
                    borderRadius: "var(--j-radius-full)",
                    border: `1px solid ${
                      draft.auto_start
                        ? "var(--j-border-glow)"
                        : "var(--j-border)"
                    }`,
                    background: draft.auto_start
                      ? "color-mix(in srgb, var(--j-cyan) 25%, transparent)"
                      : "var(--j-surface)",
                    position: "relative",
                    cursor: "pointer",
                    transition:
                      "all var(--j-duration-base) var(--j-ease-in-out)",
                    padding: 0,
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      position: "absolute",
                      top: 2,
                      left: draft.auto_start ? 24 : 2,
                      width: 20,
                      height: 20,
                      borderRadius: "var(--j-radius-full)",
                      background: draft.auto_start
                        ? "var(--j-cyan)"
                        : "var(--j-text-dim)",
                      transition:
                        "left var(--j-duration-base) var(--j-ease-in-out)",
                      boxShadow: draft.auto_start ? "var(--j-elev-1)" : "none",
                    }}
                  />
                </button>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  gap: "var(--j-space-3)",
                }}
              >
                {message && (
                  <span
                    style={{
                      fontSize: "var(--j-text-xs)",
                      fontFamily: "var(--j-font-mono)",
                      color:
                        message.tone === "error"
                          ? "var(--j-danger)"
                          : message.tone === "success"
                            ? "var(--j-success)"
                            : "var(--j-text-dim)",
                    }}
                  >
                    {message.text}
                  </span>
                )}
                <button
                  onClick={save}
                  disabled={!dirty || saving}
                  style={{
                    padding: "var(--j-space-2) var(--j-space-4)",
                    background:
                      !dirty || saving
                        ? "var(--j-surface)"
                        : "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
                    border: `1px solid ${
                      !dirty || saving
                        ? "var(--j-border)"
                        : "var(--j-border-glow)"
                    }`,
                    borderRadius: "var(--j-radius-md)",
                    color:
                      !dirty || saving ? "var(--j-text-muted)" : "var(--j-cyan)",
                    fontFamily: "var(--j-font-mono)",
                    fontSize: "var(--j-text-xs)",
                    letterSpacing: "var(--j-tracking-wide)",
                    textTransform: "uppercase",
                    cursor: !dirty || saving ? "not-allowed" : "pointer",
                    transition:
                      "all var(--j-duration-base) var(--j-ease-in-out)",
                    opacity: saving ? 0.6 : 1,
                  }}
                >
                  {saving ? "Сохраняю..." : "Применить"}
                </button>
              </div>
            </>
          ) : (
            <span
              style={{
                color:
                  message?.tone === "error"
                    ? "var(--j-danger)"
                    : "var(--j-text-muted)",
                fontSize: "var(--j-text-sm)",
              }}
            >
              {message?.text ?? "Загружаю..."}
            </span>
          )}
        </div>
      </HexFrame>
    </div>
  );
}
