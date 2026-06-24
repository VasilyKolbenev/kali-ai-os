import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActivityWidget } from "../ActivityWidget";
import { api } from "../../../../api/client";

vi.mock("../../../../api/client", () => ({
  api: { sandboxAudit: vi.fn() },
}));

function auditRow(extra: string | null) {
  return {
    id: 1,
    timestamp: 1750000000,
    backend: "in_process",
    agent: "calendar",
    action: "create_event",
    caller: "user",
    status: "ok",
    denied_reason: null,
    duration_ms: 5,
    request_id: "",
    error: null,
    extra,
  };
}

describe("ActivityWidget dry-run preview (M1.8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the plain-language label and high-risk tag (not the raw action)", async () => {
    vi.mocked(api.sandboxAudit).mockResolvedValue({
      results: [
        auditRow(
          JSON.stringify({
            preview_label: "Создаст событие в календаре от твоего имени",
            preview_risk: "high",
          }),
        ),
      ],
    } as never);

    render(<ActivityWidget />);

    expect(
      await screen.findByText("Создаст событие в календаре от твоего имени"),
    ).toBeInTheDocument();
    expect(screen.getByText("важно")).toBeInTheDocument(); // high-risk tag
  });

  it("falls back to agent: action when no preview is present", async () => {
    vi.mocked(api.sandboxAudit).mockResolvedValue({
      results: [auditRow(null)],
    } as never);

    render(<ActivityWidget />);

    expect(await screen.findByText("calendar: create_event")).toBeInTheDocument();
    expect(screen.queryByText("важно")).not.toBeInTheDocument();
  });
});
