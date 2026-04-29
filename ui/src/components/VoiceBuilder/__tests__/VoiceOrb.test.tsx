// ui/src/components/VoiceBuilder/__tests__/VoiceOrb.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VoiceOrb } from "../VoiceOrb";

describe("VoiceOrb", () => {
  it("renders the idle state with a ring", () => {
    render(<VoiceOrb state="idle" onTap={() => {}} />);
    expect(screen.getByRole("button", { name: /микрофон/i })).toBeInTheDocument();
  });

  it("calls onTap when clicked in idle / listening", () => {
    const tap = vi.fn();
    const { rerender } = render(<VoiceOrb state="idle" onTap={tap} />);
    fireEvent.click(screen.getByRole("button"));
    expect(tap).toHaveBeenCalledTimes(1);

    rerender(<VoiceOrb state="listening" onTap={tap} />);
    fireEvent.click(screen.getByRole("button"));
    expect(tap).toHaveBeenCalledTimes(2);
  });

  it("disables tap during processing", () => {
    const tap = vi.fn();
    render(<VoiceOrb state="processing" onTap={tap} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(tap).not.toHaveBeenCalled();
  });
});
