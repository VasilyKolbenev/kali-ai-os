import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveTranscript } from "../LiveTranscript";

describe("LiveTranscript", () => {
  it("renders nothing when transcript is empty", () => {
    const { container } = render(<LiveTranscript transcript="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the transcript text", () => {
    render(<LiveTranscript transcript="трекер воды" />);
    expect(screen.getByText(/трекер воды/i)).toBeInTheDocument();
  });
});
