import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HudDivider } from "../HudDivider";

describe("HudDivider", () => {
  it("renders an uppercase label when provided", () => {
    render(<HudDivider label="Section" />);
    expect(screen.getByText("Section")).toBeInTheDocument();
  });

  it("renders without label when omitted", () => {
    const { container } = render(<HudDivider />);
    const divider = container.querySelector("[data-hud='hud-divider']");
    expect(divider).not.toBeNull();
    // Only the two line spans, no label span
    expect(divider?.querySelectorAll("span").length).toBe(2);
  });
});
