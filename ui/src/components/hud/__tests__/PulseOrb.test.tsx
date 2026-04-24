import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PulseOrb } from "../PulseOrb";

describe("PulseOrb", () => {
  it("renders with default size and cyan state", () => {
    render(<PulseOrb />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-state")).toBe("active");
  });

  it("applies offline state when active={false}", () => {
    render(<PulseOrb active={false} />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-state")).toBe("offline");
  });

  it("supports danger status color", () => {
    render(<PulseOrb status="danger" />);
    const orb = screen.getByTestId("pulse-orb");
    expect(orb.getAttribute("data-status")).toBe("danger");
  });
});
