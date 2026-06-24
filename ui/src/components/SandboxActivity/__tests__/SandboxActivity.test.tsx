import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { SandboxActivity } from "../SandboxActivity";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({
  api: {
    sandboxHealth: vi.fn(),
    sandboxStats: vi.fn(),
    sandboxAudit: vi.fn(),
  },
}));

function auditRow(extra: string | null) {
  return {
    id: 1,
    timestamp: 1750000000,
    backend: "in_process",
    agent: "email",
    action: "send_email",
    caller: "user",
    status: "ok",
    denied_reason: null,
    duration_ms: 12,
    request_id: "",
    error: null,
    extra,
  };
}

describe("SandboxActivity dry-run preview (M1.8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.sandboxHealth).mockResolvedValue({
      enforcer_enabled: true,
      rate_limiter_enabled: true,
      audit_sink_enabled: true,
    } as never);
    vi.mocked(api.sandboxStats).mockResolvedValue({ results: [] } as never);
  });

  it("shows the plain-language label and the high-risk tag for an audited action", async () => {
    vi.mocked(api.sandboxAudit).mockResolvedValue({
      results: [
        auditRow(
          JSON.stringify({
            preview_label: "Отправит письмо от твоего имени",
            preview_risk: "high",
          }),
        ),
      ],
    } as never);

    render(<SandboxActivity />);

    expect(
      await screen.findByText("Отправит письмо от твоего имени"),
    ).toBeInTheDocument();
    expect(screen.getByText("важно")).toBeInTheDocument(); // high-risk tag
  });

  it("renders a row without a preview tag when extra is absent", async () => {
    vi.mocked(api.sandboxAudit).mockResolvedValue({
      results: [auditRow(null)],
    } as never);

    render(<SandboxActivity />);

    // The technical action is still shown; no preview tag is rendered.
    expect(await screen.findByText(".send_email")).toBeInTheDocument();
    expect(screen.queryByText("важно")).not.toBeInTheDocument();
  });
});
