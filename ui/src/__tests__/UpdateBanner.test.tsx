// ui/src/__tests__/UpdateBanner.test.tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { UpdateBanner } from "../components/UpdateBanner";
import { useUpdaterStore } from "../stores/updaterStore";

const manifest = {
  version: "1.0.1", pub_date: "", notes: "Исправления голоса",
  assets: [{ name: "s.exe", url: "", sha256: "", size: 4_200_000_000 }],
};

describe("UpdateBanner", () => {
  beforeEach(() => useUpdaterStore.setState(useUpdaterStore.getInitialState()));

  it("renders nothing when idle", () => {
    const { container } = render(<UpdateBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when disabled, even with a stale available manifest", () => {
    // OPUS-202: fail-closed — a lingering `available` must not surface a banner.
    useUpdaterStore.setState({ phase: "disabled", available: manifest, total: 4_200_000_000 });
    const { container } = render(<UpdateBanner />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole("button", { name: /скачать/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /перезапустить/i })).toBeNull();
  });

  it("shows version, size and notes when available", () => {
    useUpdaterStore.setState({ phase: "available", available: manifest, total: 4_200_000_000 });
    render(<UpdateBanner />);
    expect(screen.getByText(/1\.0\.1/)).toBeInTheDocument();
    expect(screen.getByText(/4[.,]2/)).toBeInTheDocument(); // размер в ГБ
    expect(screen.getByRole("button", { name: /скачать/i })).toBeInTheDocument();
  });

  it("shows progress percent while downloading", () => {
    useUpdaterStore.setState({ phase: "downloading", available: manifest, total: 100, downloaded: 37 });
    render(<UpdateBanner />);
    expect(screen.getByText(/37\s*%/)).toBeInTheDocument();
  });

  it("shows restart button when ready", () => {
    useUpdaterStore.setState({ phase: "ready", available: manifest });
    render(<UpdateBanner />);
    expect(screen.getByRole("button", { name: /перезапустить/i })).toBeInTheDocument();
  });

  it("shows error with retry", () => {
    useUpdaterStore.setState({ phase: "error", available: manifest, error: "Обрыв сети" });
    render(<UpdateBanner />);
    expect(screen.getByText(/обрыв сети/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /продолжить/i })).toBeInTheDocument();
  });

  it("hidden when dismissed", () => {
    useUpdaterStore.setState({ phase: "available", available: manifest, dismissed: true });
    const { container } = render(<UpdateBanner />);
    expect(container.firstChild).toBeNull();
  });
});
