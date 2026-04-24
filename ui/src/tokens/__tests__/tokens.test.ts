import { describe, it, expect, beforeAll } from "vitest";
import { colors } from "../index";
import "../index.css";

describe("design tokens", () => {
  beforeAll(() => {
    document.documentElement.style.cssText = document.documentElement.style.cssText;
  });

  it("TS mirror stays in sync with CSS custom properties", () => {
    const root = getComputedStyle(document.documentElement);
    expect(root.getPropertyValue("--j-cyan").trim()).toBe(colors.cyan);
    expect(root.getPropertyValue("--j-bg").trim()).toBe(colors.bg);
    expect(root.getPropertyValue("--j-offline").trim()).toBe(colors.offline);
    expect(root.getPropertyValue("--j-red").trim()).toBe(colors.red);
  });

  it("new semantic tiers are defined", () => {
    const root = getComputedStyle(document.documentElement);
    expect(root.getPropertyValue("--j-cyan-strong").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-success").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-warning").trim()).toBeTruthy();
    expect(root.getPropertyValue("--j-offline").trim()).toBeTruthy();
  });
});
