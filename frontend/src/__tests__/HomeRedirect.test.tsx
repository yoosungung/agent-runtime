import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { HomeRedirect } from "../components/HomeRedirect";
import type { UserRole } from "../lib/roles";

vi.mock("../hooks/useSession", () => ({
  useSession: vi.fn(),
}));

vi.mock("../hooks/useDashboardSummary", () => ({
  useDashboardSummary: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    isError: false,
  })),
}));

import { useSession } from "../hooks/useSession";

function renderHomeRedirect(role: UserRole) {
  vi.mocked(useSession).mockReturnValue({
    data: {
      username: "alice",
      role,
      user_id: 1,
      tenant: null,
      must_change_password: false,
    },
    isLoading: false,
    isError: false,
  } as ReturnType<typeof useSession>);

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HomeRedirect />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HomeRedirect", () => {
  it.each(["user", "developer", "admin"] as const)(
    "renders dashboard for %s role",
    (role) => {
      renderHomeRedirect(role);
      expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    },
  );
});
