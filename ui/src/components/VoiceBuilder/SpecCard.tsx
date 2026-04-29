// ui/src/components/VoiceBuilder/SpecCard.tsx
import type { BuilderPreview } from "../../api/builder";

interface Props {
  spec: BuilderPreview | null;
  highlighted: boolean;
}

const KEY_LABELS: Record<string, string> = {
  interval: "Интервал",
  goal: "Цель",
  notify_channel: "Уведомление",
  time_window: "Время",
  target: "URL",
  trigger: "Условие",
  categories: "Категории",
};

export function SpecCard({ spec, highlighted }: Props) {
  if (!spec) return null;
  const cfg = spec.config ?? {};
  return (
    <div
      data-highlighted={highlighted}
      style={{
        border: "1px solid var(--j-border)",
        borderRadius: 8,
        padding: 16,
        background: "rgba(0,224,255,0.03)",
        boxShadow: highlighted ? "0 0 16px rgba(0,224,255,0.4)" : "none",
        maxWidth: 360,
        margin: "0 auto",
        color: "var(--j-text)",
        transition: "box-shadow 0.3s",
      }}
    >
      <div>
        Тэмплейт: <span style={{ color: "var(--j-cyan)" }}>{spec.template ?? "-"}</span>
      </div>
      <div>
        Имя: <span style={{ color: "var(--j-cyan)" }}>{spec.name}</span>
      </div>
      <div>
        Описание: <span style={{ color: "var(--j-cyan)" }}>{spec.description}</span>
      </div>
      {Object.entries(KEY_LABELS).map(([k, label]) => {
        const val = cfg[k];
        return (
          <div key={k}>
            {label}:{" "}
            {val ? (
              <span style={{ color: "var(--j-cyan)" }}>{String(val)}</span>
            ) : (
              <span style={{ color: "var(--j-text-dim)" }}>?</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
