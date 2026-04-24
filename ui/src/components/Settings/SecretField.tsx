import { useState } from "react";

type Status = "unknown" | "checking" | "valid" | "invalid";

interface SecretFieldProps {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onTest?: () => void;
  status?: Status;
}

export function SecretField({
  value,
  onChange,
  placeholder,
  onTest,
  status = "unknown",
}: SecretFieldProps) {
  const [visible, setVisible] = useState(false);

  const statusLabel =
    status === "valid"
      ? "● активен"
      : status === "invalid"
        ? "● ошибка"
        : status === "checking"
          ? "● проверяю..."
          : "○ не настроен";
  const statusColor =
    status === "valid"
      ? "var(--j-success)"
      : status === "invalid"
        ? "var(--j-danger)"
        : status === "checking"
          ? "var(--j-amber)"
          : "var(--j-text-muted)";

  return (
    <div className="flex items-center gap-2 w-full">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          flex: 1,
          padding: "var(--j-space-2) var(--j-space-3)",
          background: "var(--j-surface)",
          border: "1px solid var(--j-border)",
          borderRadius: "var(--j-radius-md)",
          color: "var(--j-text)",
          fontFamily: "var(--j-font-mono)",
          fontSize: "var(--j-text-sm)",
        }}
      />
      <button
        onClick={() => setVisible(!visible)}
        title={visible ? "Скрыть" : "Показать"}
        aria-label={visible ? "Скрыть" : "Показать"}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--j-text-dim)",
          cursor: "pointer",
          fontSize: "var(--j-text-sm)",
        }}
      >
        {visible ? "🙈" : "👁"}
      </button>
      {onTest && (
        <button
          onClick={onTest}
          disabled={!value || status === "checking"}
          style={{
            padding: "var(--j-space-2) var(--j-space-3)",
            background: "color-mix(in srgb, var(--j-cyan) 12%, transparent)",
            border: "1px solid var(--j-border-glow)",
            borderRadius: "var(--j-radius-md)",
            color: "var(--j-cyan)",
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: "pointer",
          }}
        >
          Проверить
        </button>
      )}
      <span
        style={{
          fontSize: "var(--j-text-xs)",
          color: statusColor,
          fontFamily: "var(--j-font-mono)",
          minWidth: "110px",
        }}
      >
        {statusLabel}
      </span>
    </div>
  );
}
