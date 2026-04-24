import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HexFrame } from "../HexFrame";

describe("HexFrame", () => {
  it("renders children inside a clip-path container", () => {
    render(<HexFrame><span>hello</span></HexFrame>);
    const inner = screen.getByText("hello");
    const frame = inner.closest("[data-hud='hex-frame']") as HTMLElement;
    expect(frame).not.toBeNull();
    expect(frame.style.clipPath).toContain("polygon");
  });

  it("applies `active` glow when prop is true", () => {
    render(<HexFrame active><span>x</span></HexFrame>);
    const frame = screen.getByText("x").closest("[data-hud='hex-frame']") as HTMLElement;
    expect(frame.getAttribute("data-active")).toBe("true");
  });
});
