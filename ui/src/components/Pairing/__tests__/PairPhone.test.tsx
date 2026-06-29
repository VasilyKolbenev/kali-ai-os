import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PairPhone } from "../PairPhone";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({
  api: {
    pairingToken: vi.fn(),
    pairingLanIp: vi.fn(),
  },
}));

describe("PairPhone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the QR link from token + LAN IP when LAN is enabled", async () => {
    vi.mocked(api.pairingToken).mockResolvedValue({ token: "deadbeef", path: "/x" });
    vi.mocked(api.pairingLanIp).mockResolvedValue({ ip: "192.168.1.42", lan_enabled: true });

    render(<PairPhone />);

    await waitFor(() => {
      expect(
        screen.getByText("kali://pair?ip=192.168.1.42&token=deadbeef"),
      ).toBeInTheDocument();
    });
    // Camera instruction is shown.
    expect(screen.getByText(/Наведите камеру телефона/)).toBeInTheDocument();
  });

  it("shows the enable-LAN + restart prompt when LAN is disabled", async () => {
    vi.mocked(api.pairingToken).mockResolvedValue({ token: "deadbeef", path: "/x" });
    vi.mocked(api.pairingLanIp).mockResolvedValue({ ip: "192.168.1.42", lan_enabled: false });

    render(<PairPhone />);

    await waitFor(() => {
      expect(screen.getByText("KALI_LAN=1")).toBeInTheDocument();
    });
    // No QR link is shown when unreachable.
    expect(screen.queryByText(/kali:\/\/pair/)).not.toBeInTheDocument();
  });

  it("treats a missing LAN IP as unreachable even if lan_enabled is true", async () => {
    vi.mocked(api.pairingToken).mockResolvedValue({ token: "deadbeef", path: "/x" });
    vi.mocked(api.pairingLanIp).mockResolvedValue({ ip: null, lan_enabled: true });

    render(<PairPhone />);

    await waitFor(() => {
      expect(screen.getByText(/Не найден сетевой адрес/)).toBeInTheDocument();
    });
  });

  it("surfaces a fetch error", async () => {
    vi.mocked(api.pairingToken).mockRejectedValue(new Error("boom"));
    vi.mocked(api.pairingLanIp).mockResolvedValue({ ip: "192.168.1.42", lan_enabled: true });

    render(<PairPhone />);

    await waitFor(() => {
      expect(screen.getByText(/Не удалось получить данные/)).toBeInTheDocument();
    });
  });
});
