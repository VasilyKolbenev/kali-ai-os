import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecretField } from "../SecretField";

describe("SecretField", () => {
  it("masks value by default and toggles on show", async () => {
    const user = userEvent.setup();
    render(<SecretField value="abc123" onChange={() => {}} placeholder="sk-..." />);
    const input = screen.getByPlaceholderText("sk-...") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.click(screen.getByRole("button", { name: /показать/i }));
    expect(input.type).toBe("text");
  });

  it("calls onTest when test button clicked", async () => {
    const user = userEvent.setup();
    const onTest = vi.fn();
    render(
      <SecretField value="k" onChange={() => {}} placeholder="x" onTest={onTest} />,
    );
    await user.click(screen.getByRole("button", { name: /проверить/i }));
    expect(onTest).toHaveBeenCalledOnce();
  });

  it("renders status indicator with given status", () => {
    render(
      <SecretField value="k" onChange={() => {}} placeholder="x" status="valid" />,
    );
    expect(screen.getByText(/активен/i)).toBeInTheDocument();
  });

  it("test button disabled when value empty", () => {
    render(
      <SecretField value="" onChange={() => {}} placeholder="x" onTest={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /проверить/i })).toBeDisabled();
  });
});
