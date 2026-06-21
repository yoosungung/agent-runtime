import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AccessList } from "../components/AccessList";

const mockInvalidateQueries = vi.fn();
const mockUseSourceMetaAccess = vi.fn();

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => ({
      invalidateQueries: mockInvalidateQueries,
    }),
  };
});

vi.mock("../hooks/useSourceMeta", () => ({
  useSourceMetaAccess: (...args: unknown[]) => mockUseSourceMetaAccess(...args),
}));

vi.mock("../components/UserSearchInput", () => ({
  UserSearchInput: ({
    onSelect,
  }: {
    onSelect: (user: { id: number; username: string }) => void;
  }) => (
    <button type="button" onClick={() => onSelect({ id: 4, username: "user" })}>
      Add test user
    </button>
  ),
}));

vi.mock("../lib/api", () => ({
  apiJson: vi.fn().mockResolvedValue(undefined),
}));

import { apiJson } from "../lib/api";

function renderResourceAccess() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AccessList sourceMetaId={2} kind="mcp" name="utility-server" />
    </QueryClientProvider>,
  );
}

describe("AccessList resource view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSourceMetaAccess.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isError: false,
    });
  });

  it("invalidates source-meta access query after granting user access", async () => {
    const user = userEvent.setup();
    renderResourceAccess();

    await user.click(screen.getByRole("button", { name: "Add test user" }));

    await waitFor(() => {
      expect(apiJson).toHaveBeenCalledWith("/api/users/4/access", {
        method: "POST",
        body: JSON.stringify({ kind: "mcp", name: "utility-server" }),
      });
    });

    expect(mockInvalidateQueries).toHaveBeenCalledWith({
      queryKey: ["source-meta", 2, "access"],
    });
    expect(mockInvalidateQueries).toHaveBeenCalledWith({
      queryKey: ["users", 4, "access"],
    });
  });
});
