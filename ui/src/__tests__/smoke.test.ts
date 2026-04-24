import { describe, it, expect } from "vitest";

describe("test infrastructure", () => {
  it("runs vitest + jsdom", () => {
    const div = document.createElement("div");
    div.textContent = "hello";
    expect(div.textContent).toBe("hello");
  });

  it("exposes matchers from jest-dom", () => {
    document.body.innerHTML = '<button disabled>x</button>';
    const btn = document.querySelector("button")!;
    expect(btn).toBeDisabled();
  });
});
