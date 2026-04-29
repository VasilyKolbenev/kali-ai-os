// ui/src/components/VoiceBuilder/__tests__/SpecCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpecCard } from "../SpecCard";
import type { BuilderPreview } from "../../../api/builder";

const _spec = (config: Record<string, unknown> = {}): BuilderPreview => ({
  name: "treker-vody",
  description: "трекер",
  type: "skill",
  template: "tracker",
  config,
});

describe("SpecCard", () => {
  it("renders empty fields muted when config is empty", () => {
    render(<SpecCard spec={_spec()} highlighted={false} />);
    expect(screen.getByText(/Тэмплейт:/)).toBeInTheDocument();
    expect(screen.getByText(/трекер/)).toBeInTheDocument();
  });

  it("highlights filled config keys", () => {
    render(
      <SpecCard
        spec={_spec({ interval: "2 часа", goal: "2 литра" })}
        highlighted={false}
      />,
    );
    expect(screen.getByText(/2 часа/)).toBeInTheDocument();
    expect(screen.getByText(/2 литра/)).toBeInTheDocument();
  });

  it("applies the highlighted style during preview", () => {
    const { container } = render(
      <SpecCard spec={_spec()} highlighted={true} />,
    );
    expect(container.firstChild).toHaveAttribute("data-highlighted", "true");
  });

  it("returns null when spec is null", () => {
    const { container } = render(<SpecCard spec={null} highlighted={false} />);
    expect(container.firstChild).toBeNull();
  });
});
