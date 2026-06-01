import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

export function TableWidget({ widget }: Props) {
  const headers = (widget.data.headers as string[] | undefined) ?? [];
  const rows = (widget.data.rows as string[][] | undefined) ?? [];

  return (
    <div className="glass p-5 flex flex-col gap-3">
      <div
        className="mono text-[10px] tracking-[2px] uppercase"
        style={{ color: "var(--j-text-muted)" }}
      >
        {widget.title}
      </div>
      <div className="overflow-auto" style={{ maxHeight: 240 }}>
        <table className="w-full border-collapse">
          {headers.length > 0 && (
            <thead>
              <tr>
                {headers.map((h) => (
                  <th
                    key={h}
                    className="mono text-[10px] font-semibold uppercase tracking-wider text-left px-3 py-2"
                    style={{
                      color: "var(--j-text-dim)",
                      borderBottom: "1px solid rgba(255,255,255,0.06)",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {rows.map((row, ri) => (
              <tr
                key={ri}
                className="transition-colors duration-150"
                style={{ background: ri % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(0,212,255,0.04)")}
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background =
                    ri % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)")
                }
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="mono text-xs px-3 py-2"
                    style={{
                      color: "var(--j-text)",
                      borderBottom: "1px solid rgba(255,255,255,0.03)",
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mono text-[9px]" style={{ color: "var(--j-text-muted)" }}>
        {rows.length} строк
      </div>
    </div>
  );
}
