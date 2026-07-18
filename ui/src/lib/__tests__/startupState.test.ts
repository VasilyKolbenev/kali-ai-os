import { describe, expect, it } from "vitest";
import { classifyStartup } from "../startupState";

/** Every contract label that must render an overlay, with its required routing. */
const OVERLAY: ReadonlyArray<[label: string, kind: "failed" | "degraded", reason: string]> = [
  ["degraded:not_found", "failed", "not_found"],
  ["degraded:port_occupied", "failed", "port_occupied"],
  ["degraded:crashed", "degraded", "crashed"],
  ["degraded:foreign_backend", "degraded", "foreign_backend"],
  ["degraded:spawn_failed", "degraded", "spawn_failed"],
  ["degraded:process_unknown", "degraded", "process_unknown"],
  ["failed:rust_startup", "failed", "rust_startup"],
  ["failed:gave_up", "failed", "gave_up"],
  ["failed", "failed", "generic"],
];

const FORBIDDEN_PLACEHOLDER = /TODO|PENDING|PLACEHOLDER/i;

describe("classifyStartup", () => {
  it("null и booting-лейблы → booting (без оверлея)", () => {
    for (const l of [null, "shell_ready", "rust_ready", "python_starting"]) {
      expect(classifyStartup(l).kind).toBe("booting");
    }
  });

  it("python_ready → ready", () => {
    expect(classifyStartup("python_ready").kind).toBe("ready");
  });

  it.each(OVERLAY)("%s → %s/%s", (label, kind, reason) => {
    const v = classifyStartup(label);
    expect(v.kind).toBe(kind);
    expect(v.reason).toBe(reason);
  });

  it("not_found и port_occupied — КРАСНЫЕ, несмотря на префикс degraded:", () => {
    expect(classifyStartup("degraded:not_found").kind).toBe("failed");
    expect(classifyStartup("degraded:port_occupied").kind).toBe("failed");
  });

  it("любой неизвестный non-null label → failed/protocol_error (никогда booting)", () => {
    for (const l of ["wat:nonsense", "degraded:brand_new", "python_starting_v2", ""]) {
      const v = classifyStartup(l);
      expect(v.kind).toBe("failed");
      expect(v.reason).toBe("protocol_error");
    }
  });

  it("каждый overlay-лейбл даёт различимую реальную копию", () => {
    const views = [
      ...OVERLAY.map(([l]) => classifyStartup(l)),
      classifyStartup("wat:unknown"), // + protocol_error
    ];
    const keys = new Set(views.map((v) => `${v.title}|${v.body}`));
    expect(keys.size).toBe(views.length); // все различны
    for (const v of views) {
      expect(v.title.trim().length).toBeGreaterThan(0);
      expect(v.body.trim().length).toBeGreaterThan(0);
      expect(v.title.trim()).not.toBe("…"); // голое многоточие = незаполненный слот
      expect(v.body.trim()).not.toBe("…");
      expect(v.title).not.toMatch(FORBIDDEN_PLACEHOLDER);
      expect(v.body).not.toMatch(FORBIDDEN_PLACEHOLDER);
    }
  });

  it("booting/ready не несут копию", () => {
    expect(classifyStartup("python_ready").title).toBe("");
    expect(classifyStartup(null).title).toBe("");
  });
});
