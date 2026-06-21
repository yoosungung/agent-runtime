import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { Layout } from "../components/Layout";
import type { UserRole } from "../lib/roles";

vi.mock("../hooks/useSession", () => ({
  useSession: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  apiJson: vi.fn(),
}));

import { useSession } from "../hooks/useSession";

function renderLayout(role: UserRole, initialPath = "/agents") {
  vi.mocked(useSession).mockReturnValue({
    data: { username: "alice", role, user_id: 1, tenant: null, must_change_password: false },
  } as ReturnType<typeof useSession>);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Layout navigation", () => {
  it("shows user menu items only for user role", () => {
    renderLayout("user");
    expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agent" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bundle" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "User" })).not.toBeInTheDocument();
  });

  it("shows developer menu items for developer role", () => {
    renderLayout("developer");
    expect(screen.getByRole("link", { name: "Bundle" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Container" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "User" })).not.toBeInTheDocument();
  });

  it("shows admin menu items for admin role", () => {
    renderLayout("admin");
    expect(screen.getByRole("link", { name: "User" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Audit" })).toBeInTheDocument();
  });

  it("locks viewport height on chat route for inner scroll panes", () => {
    renderLayout("user", "/chat");
    const shell = screen.getByRole("main").parentElement;
    expect(shell).toHaveClass("h-screen");
    expect(shell).toHaveClass("overflow-hidden");
    expect(screen.getByRole("main")).toHaveClass("overflow-hidden");
  });
});
