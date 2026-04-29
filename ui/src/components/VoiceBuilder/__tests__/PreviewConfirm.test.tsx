// ui/src/components/VoiceBuilder/__tests__/PreviewConfirm.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { PreviewConfirm } from "../PreviewConfirm";
import type { BuilderPreview } from "../../../api/builder";

const _say = vi.fn();
const _deploy = vi.fn();
const _cancel = vi.fn();

vi.mock("../../../api/builder", () => ({
  builderApi: { say: (...args: any[]) => _say(...args) },
}));
const _setPreviewSubState = vi.fn();
vi.mock("../../../stores/builder", () => ({
  useBuilderStore: () => ({ deploy: _deploy, cancel: _cancel, setPreviewSubState: _setPreviewSubState }),
}));

const _spec: BuilderPreview = {
  name: "treker-vody",
  description: "трекер",
  type: "skill",
  template: "tracker",
  config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
};

describe("PreviewConfirm", () => {
  beforeEach(() => {
    _say.mockReset().mockResolvedValue({ status: "ok", duration: 2 });
    _deploy.mockReset();
    _cancel.mockReset();
  });

  it("speaks the spec on mount", async () => {
    render(<PreviewConfirm spec={_spec} />);
    await waitFor(() => expect(_say).toHaveBeenCalled());
    const text = (_say.mock.calls[0][0] as string).toLowerCase();
    expect(text).toContain("treker-vody");
    expect(text).toContain("2 часа");
  });

  it("renders deploy + cancel buttons (a11y fallback)", () => {
    render(<PreviewConfirm spec={_spec} />);
    expect(screen.getByRole("button", { name: /запустить/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /отмена/i })).toBeInTheDocument();
  });

  it("clicking deploy fires store.deploy()", () => {
    render(<PreviewConfirm spec={_spec} />);
    fireEvent.click(screen.getByRole("button", { name: /запустить/i }));
    expect(_deploy).toHaveBeenCalledTimes(1);
  });
});
