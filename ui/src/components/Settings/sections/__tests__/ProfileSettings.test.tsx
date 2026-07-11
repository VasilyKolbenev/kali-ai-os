import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProfileSettings } from "../ProfileSettings";

const profile = vi.fn().mockResolvedValue({
  name: "Вася", gender: "male", occupation: null, city: "Ереван", age_range: null,
});
const updateProfile = vi.fn().mockResolvedValue({ status: "ok", saved: [] });
vi.mock("../../../../api/client", () => ({
  api: {
    profile: (...a: unknown[]) => profile(...a),
    updateProfile: (...a: unknown[]) => updateProfile(...a),
  },
}));

beforeEach(() => { updateProfile.mockClear(); });

describe("ProfileSettings", () => {
  it("prefills from GET /profile", async () => {
    render(<ProfileSettings />);
    await waitFor(() => expect(screen.getByLabelText("Имя")).toHaveValue("Вася"));
    expect(screen.getByLabelText("Город")).toHaveValue("Ереван");
  });

  it("save posts edited fields including explicit clears", async () => {
    render(<ProfileSettings />);
    await waitFor(() => expect(screen.getByLabelText("Имя")).toHaveValue("Вася"));
    fireEvent.change(screen.getByLabelText("Город"), { target: { value: "" } });
    fireEvent.click(screen.getByText("Сохранить профиль"));
    await waitFor(() => expect(updateProfile).toHaveBeenCalled());
    const patch = updateProfile.mock.calls[0][0] as Record<string, string>;
    expect(patch.city).toBe("");  // explicit clear deletes the fact
  });
});
