import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FadeSlideUp } from "../FadeSlideUp";

describe("FadeSlideUp", () => {
  it("renders children", () => {
    render(<FadeSlideUp>hello</FadeSlideUp>);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("applies the data-motion attribute for debugging", () => {
    render(<FadeSlideUp>x</FadeSlideUp>);
    expect(screen.getByText("x").closest("[data-motion]")).not.toBeNull();
  });
});
