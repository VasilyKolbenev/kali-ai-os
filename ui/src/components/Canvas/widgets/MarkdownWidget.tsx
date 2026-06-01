import React from "react";
import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

function parseInline(text: string, keyPrefix: string) {
  // Simple regex matching for bold, italic, code
  const parts = [];
  let current = "";
  let i = 0;
  
  while (i < text.length) {
    if (text.startsWith("**", i)) {
      if (current) parts.push(<React.Fragment key={`${keyPrefix}-t${i}`}>{current}</React.Fragment>);
      current = "";
      const end = text.indexOf("**", i + 2);
      if (end !== -1) {
        parts.push(<strong key={`${keyPrefix}-b${i}`} style={{ color: "var(--j-text)" }}>{text.slice(i + 2, end)}</strong>);
        i = end + 2;
      } else {
        current += "**";
        i += 2;
      }
    } else if (text.startsWith("*", i) && text[i+1] !== "*") {
      if (current) parts.push(<React.Fragment key={`${keyPrefix}-t${i}`}>{current}</React.Fragment>);
      current = "";
      const end = text.indexOf("*", i + 1);
      if (end !== -1) {
        parts.push(<em key={`${keyPrefix}-i${i}`}>{text.slice(i + 1, end)}</em>);
        i = end + 1;
      } else {
        current += "*";
        i += 1;
      }
    } else if (text.startsWith("`", i)) {
      if (current) parts.push(<React.Fragment key={`${keyPrefix}-t${i}`}>{current}</React.Fragment>);
      current = "";
      const end = text.indexOf("`", i + 1);
      if (end !== -1) {
        parts.push(<code key={`${keyPrefix}-c${i}`} style={{ background: "var(--j-surface)", padding: "1px 4px", borderRadius: "3px", fontSize: "11px" }}>{text.slice(i + 1, end)}</code>);
        i = end + 1;
      } else {
        current += "`";
        i += 1;
      }
    } else {
      current += text[i];
      i++;
    }
  }
  if (current) parts.push(<React.Fragment key={`${keyPrefix}-tend`}>{current}</React.Fragment>);
  return parts;
}

export function MarkdownWidget({ widget }: Props) {
  const content = String(widget.data.content ?? "");

  const rendered = content.split("\n").map((line, index) => {
    const key = `line-${index}`;
    
    if (line.startsWith("### ")) {
      return <h4 key={key} style={{ margin: "8px 0 4px", fontSize: "13px", color: "var(--j-text)" }}>{parseInline(line.slice(4), key)}</h4>;
    }
    if (line.startsWith("## ")) {
      return <h3 key={key} style={{ margin: "10px 0 4px", fontSize: "14px", color: "var(--j-text)" }}>{parseInline(line.slice(3), key)}</h3>;
    }
    if (line.startsWith("# ")) {
      return <h2 key={key} style={{ margin: "12px 0 6px", fontSize: "16px", color: "var(--j-cyan)" }}>{parseInline(line.slice(2), key)}</h2>;
    }
    if (line.startsWith("- ")) {
      return <div key={key} style={{ paddingLeft: "12px", margin: "2px 0" }}>• {parseInline(line.slice(2), key)}</div>;
    }
    if (/^\d+\. /.test(line)) {
      return <div key={key} style={{ paddingLeft: "12px", margin: "2px 0" }}>{parseInline(line, key)}</div>;
    }
    if (!line.trim()) {
      return <br key={key} />;
    }
    
    return <div key={key} style={{ margin: "2px 0" }}>{parseInline(line, key)}</div>;
  });

  return (
    <div className="glass p-5 flex flex-col gap-2">
      <div
        className="mono text-[10px] tracking-[2px] uppercase"
        style={{ color: "var(--j-text-muted)" }}
      >
        {widget.title}
      </div>
      <div
        className="mono text-xs leading-relaxed"
        style={{ color: "var(--j-text-dim)" }}
      >
        {rendered}
      </div>
    </div>
  );
}
