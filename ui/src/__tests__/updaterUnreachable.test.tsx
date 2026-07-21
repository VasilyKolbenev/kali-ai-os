// OPUS-202: the disabled custom updater must be unreachable from the production
// App tree — no auto-check on mount or after a 24h timer, and UpdateBanner is
// not rendered at all.
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { startupLabel, gate, checkSpy } = vi.hoisted(() => ({
  startupLabel: vi.fn<() => string | null>(),
  gate: vi.fn<() => { loading: boolean; gated: boolean; slow: boolean }>(),
  checkSpy: vi.fn(),
}));

vi.mock("../hooks/useStartupState", () => ({ useStartupState: () => startupLabel() }));
vi.mock("../hooks/useOnboardingGate", () => ({ useOnboardingGate: () => gate() }));
vi.mock("../api/websocket", () => ({ useWebSocket: () => {} }));
// If a regression re-adds the on-mount/24h auto-check, this selector-based mock's
// `check` spy fires → the tests below go red.
vi.mock("../stores/updaterStore", () => ({
  useUpdaterStore: (sel: (s: unknown) => unknown) => sel({ check: checkSpy }),
}));
// Sentinel: if UpdateBanner is re-added to the App tree, this testid appears.
vi.mock("../components/UpdateBanner", () => ({
  UpdateBanner: () => <div data-testid="update-banner-sentinel" />,
}));

import App from "../App";

describe("OPUS-202: updater unreachable from App", () => {
  beforeEach(() => {
    startupLabel.mockReturnValue(null);
    gate.mockReturnValue({ loading: false, gated: false, slow: false });
    checkSpy.mockClear();
  });
  afterEach(() => vi.useRealTimers());

  it("does not call updater.check on mount", () => {
    render(<App />);
    expect(checkSpy).not.toHaveBeenCalled();
  });

  it("does not call updater.check after a 24h timer", () => {
    vi.useFakeTimers();
    render(<App />);
    vi.advanceTimersByTime(24 * 3600 * 1000 + 1000);
    expect(checkSpy).not.toHaveBeenCalled();
  });

  it("does not render UpdateBanner in the App tree", () => {
    const { queryByTestId } = render(<App />);
    expect(queryByTestId("update-banner-sentinel")).toBeNull();
  });
});
