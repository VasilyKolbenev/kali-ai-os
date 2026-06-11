import { useEffect } from "react";
import { useCanvasStore } from "../../stores/canvasStore";
import type { CanvasWidget } from "../../stores/canvasStore";
import { api } from "../../api/client";
import { StatCardWidget } from "./widgets/StatCardWidget";
import { BarChartWidget } from "./widgets/BarChartWidget";
import { LineChartWidget } from "./widgets/LineChartWidget";
import { ProgressWidget } from "./widgets/ProgressWidget";
import { TableWidget } from "./widgets/TableWidget";
import { MarkdownWidget } from "./widgets/MarkdownWidget";
import { motion, AnimatePresence } from "framer-motion";

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
};

const item = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: "spring", bounce: 0.35, duration: 0.6 },
  },
  exit: { opacity: 0, scale: 0.9, transition: { duration: 0.2 } },
};

function WidgetRenderer({ widget }: { widget: CanvasWidget }) {
  switch (widget.type) {
    case "stat_card":
      return <StatCardWidget widget={widget} />;
    case "bar_chart":
      return <BarChartWidget widget={widget} />;
    case "line_chart":
      return <LineChartWidget widget={widget} />;
    case "progress":
      return <ProgressWidget widget={widget} />;
    case "table":
      return <TableWidget widget={widget} />;
    case "markdown":
      return <MarkdownWidget widget={widget} />;
    default:
      return (
        <div className="glass p-5">
          <div className="mono text-xs" style={{ color: "var(--j-text-muted)" }}>
            Неизвестный виджет: {widget.type}
          </div>
        </div>
      );
  }
}

/** Determine grid span: tables and markdown take full width. */
function gridClass(type: string): string {
  if (type === "table" || type === "markdown") return "col-span-2 lg:col-span-3";
  return "";
}

/** Live widget grid — embeddable (Сводка hosts it below the fixed widgets). */
export function CanvasSection({ hideWhenEmpty = false }: { hideWhenEmpty?: boolean }) {
  const widgets = useCanvasStore((s) => s.widgets);
  const setWidgets = useCanvasStore((s) => s.setWidgets);

  // Initial load from REST (WebSocket handles real-time after)
  useEffect(() => {
    api
      .canvasWidgets()
      .then((res) => {
        if (res.widgets?.length) setWidgets(res.widgets);
      })
      .catch(() => {
        /* kernel not running — keep empty */
      });
  }, [setWidgets]);

  if (widgets.length === 0 && hideWhenEmpty) return null;

  return (
    <>
      {/* Empty state */}
      {widgets.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass p-12 flex flex-col items-center gap-4"
        >
          <div className="text-4xl opacity-40">🎨</div>
          <div className="mono text-sm text-center" style={{ color: "var(--j-text-dim)" }}>
            Пока пусто
          </div>
          <div
            className="mono text-[11px] text-center max-w-md leading-relaxed"
            style={{ color: "var(--j-text-muted)" }}
          >
            Скажите <strong style={{ color: "var(--j-cyan)" }}>«Jarvis, покажи расходы за неделю графиком»</strong> или{" "}
            <strong style={{ color: "var(--j-cyan)" }}>«нарисуй статистику задач»</strong> — и виджеты появятся здесь.
          </div>
        </motion.div>
      )}

      {/* Widget grid */}
      {widgets.length > 0 && (
        <motion.div
          className="grid grid-cols-2 lg:grid-cols-3 gap-4"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <AnimatePresence mode="popLayout">
            {widgets.map((w) => (
              <motion.div
                key={w.id}
                variants={item}
                layout
                exit={item.exit}
                className={`${gridClass(w.type)} hover:scale-[1.01] transition-transform duration-200`}
              >
                <WidgetRenderer widget={w} />
              </motion.div>
            ))}
          </AnimatePresence>
        </motion.div>
      )}
    </>
  );
}

export function Canvas() {
  const widgets = useCanvasStore((s) => s.widgets);

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-8">
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Canvas
          </h2>
          <span
            className="mono text-[10px] tracking-widest uppercase"
            style={{ color: "var(--j-text-muted)" }}
          >
            Динамические виджеты
          </span>
          {widgets.length > 0 && (
            <span
              className="ml-auto mono text-[10px] px-2 py-0.5 rounded-full"
              style={{
                background: "rgba(0,212,255,0.1)",
                color: "var(--j-cyan)",
                border: "1px solid rgba(0,212,255,0.15)",
              }}
            >
              {widgets.length} виджетов
            </span>
          )}
        </div>

        <CanvasSection />
      </div>
    </div>
  );
}
