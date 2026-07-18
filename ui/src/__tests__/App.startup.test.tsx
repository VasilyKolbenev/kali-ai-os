import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { startupLabel, gate } = vi.hoisted(() => ({
  startupLabel: vi.fn<() => string | null>(),
  gate: vi.fn<() => { loading: boolean; gated: boolean; slow: boolean }>(),
}));

vi.mock("../hooks/useStartupState", () => ({ useStartupState: () => startupLabel() }));
vi.mock("../hooks/useOnboardingGate", () => ({ useOnboardingGate: () => gate() }));
vi.mock("../api/websocket", () => ({ useWebSocket: () => {} }));
vi.mock("../stores/updaterStore", () => ({
  useUpdaterStore: (sel: (s: unknown) => unknown) => sel({ check: () => Promise.resolve() }),
}));

import App from "../App";

describe("App startup surface", () => {
  beforeEach(() => {
    startupLabel.mockReturnValue(null);
    gate.mockReturnValue({ loading: true, gated: true, slow: false });
  });

  it("U1: янтарный degraded перекрывает бесконечный onboarding-сплэш", () => {
    startupLabel.mockReturnValue("degraded:crashed");
    render(<App />);
    expect(screen.getByTestId("startup-degraded")).toBeInTheDocument();
    expect(screen.queryByText(/Джарвис запускается/)).not.toBeInTheDocument();
  });

  it("U2: failed перекрывает onboarding-мастер", () => {
    startupLabel.mockReturnValue("failed:rust_startup");
    gate.mockReturnValue({ loading: false, gated: true, slow: false });
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
  });

  it("U3: booting оставляет boot-сплэш (оверлей отделён от загрузки моделей)", () => {
    startupLabel.mockReturnValue("python_starting");
    render(<App />);
    expect(screen.getByText(/Джарвис запускается/)).toBeInTheDocument();
    expect(screen.queryByTestId("startup-degraded")).not.toBeInTheDocument();
    expect(screen.queryByTestId("startup-failed")).not.toBeInTheDocument();
  });

  it("U4: degraded:not_found рендерится КРАСНЫМ, не янтарным", () => {
    startupLabel.mockReturnValue("degraded:not_found");
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
    expect(screen.queryByTestId("startup-degraded")).not.toBeInTheDocument();
  });

  it("U5: неизвестный label рендерит красный protocol-error", () => {
    startupLabel.mockReturnValue("wat:nonsense");
    render(<App />);
    expect(screen.getByTestId("startup-failed")).toBeInTheDocument();
    expect(screen.getByText(/Не удалось определить состояние запуска/)).toBeInTheDocument();
  });
});
