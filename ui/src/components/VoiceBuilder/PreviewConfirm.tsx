import { useEffect } from "react";
import { builderApi, type BuilderPreview } from "../../api/builder";
import { useBuilderStore } from "../../stores/builder";
import { SpecCard } from "./SpecCard";

const KEY_LABELS: Record<string, string> = {
  interval: "интервал",
  goal: "цель",
  notify_channel: "уведомление",
  time_window: "время",
  target: "url",
  trigger: "условие",
  categories: "категории",
};

const _buildReadbackText = (spec: BuilderPreview): string => {
  const parts = [`создаю ${spec.name}`];
  for (const [k, v] of Object.entries(spec.config ?? {})) {
    if (!v) continue;
    const label = KEY_LABELS[k] ?? k;
    parts.push(`${label} ${String(v)}`);
  }
  parts.push("подтверди");
  return parts.join(", ");
};

interface Props {
  spec: BuilderPreview;
}

export function PreviewConfirm({ spec }: Props) {
  const { deploy, cancel, setPreviewSubState } = useBuilderStore();

  useEffect(() => {
    let cancelled = false;
    // Awaits the full /tts/speak round-trip — Python's endpoint
    // returns only after audio playback finishes (`await
    // asyncio.to_thread(_play_audio, audio, sr)` at main.py:1418), so
    // by the time `say` resolves the speakers are silent and it's safe
    // to start mic capture without echoing the readback into STT.
    void builderApi
      .say(_buildReadbackText(spec), "ru")
      .finally(() => {
        if (!cancelled) setPreviewSubState("listening_for_command");
      });
    return () => {
      cancelled = true;
    };
  }, [spec, setPreviewSubState]);

  return (
    <div style={{ textAlign: "center" }}>
      <SpecCard spec={spec} highlighted={true} />
      <div style={{ marginTop: 24, display: "flex", gap: 12, justifyContent: "center" }}>
        <button
          type="button"
          onClick={() => void deploy()}
          style={{
            padding: "12px 24px",
            background: "var(--j-cyan)",
            color: "var(--j-bg)",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          Запустить
        </button>
        <button
          type="button"
          onClick={() => void cancel()}
          style={{
            padding: "12px 24px",
            background: "transparent",
            color: "var(--j-text-dim)",
            border: "1px solid var(--j-border)",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
