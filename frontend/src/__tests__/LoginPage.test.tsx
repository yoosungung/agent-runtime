import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "../pages/LoginPage";

const navigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock("../lib/api", () => ({
  apiJson: vi.fn(),
}));

import { apiJson } from "../lib/api";

describe("LoginPage", () => {
  it("redirects to dashboard after login", async () => {
    vi.mocked(apiJson).mockResolvedValue({
      user_id: 2,
      username: "dev1",
      role: "developer",
      must_change_password: false,
    });

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByRole("textbox"), "dev1");
    await userEvent.type(
      document.querySelector('input[type="password"]') as HTMLInputElement,
      "secret",
    );
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(navigate).toHaveBeenCalledWith("/", { replace: true });
  });

  it("redirects to profile when password change is required", async () => {
    vi.mocked(apiJson).mockResolvedValue({
      user_id: 2,
      username: "dev1",
      role: "developer",
      must_change_password: true,
    });

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByRole("textbox"), "dev1");
    await userEvent.type(
      document.querySelector('input[type="password"]') as HTMLInputElement,
      "secret",
    );
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(navigate).toHaveBeenCalledWith("/me", { replace: true });
  });
});
