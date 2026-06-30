import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MyApiKeysPanel } from "../components/MyApiKeysPanel";

const mockUseMyApiKeys = vi.fn();
const mockCreateMutateAsync = vi.fn();
const mockDisableMutateAsync = vi.fn();

vi.mock("../hooks/useMyApiKeys", () => ({
  useMyApiKeys: () => mockUseMyApiKeys(),
  useCreateMyApiKey: () => ({
    mutateAsync: mockCreateMutateAsync,
    isPending: false,
  }),
  useDisableMyApiKey: () => ({
    mutateAsync: mockDisableMutateAsync,
    isPending: false,
  }),
}));

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MyApiKeysPanel />
    </QueryClientProvider>,
  );
}

describe("MyApiKeysPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMyApiKeys.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isError: false,
    });
    mockCreateMutateAsync.mockResolvedValue({
      id: 1,
      name: "path-graph-pipeline",
      key: "ak_1_secretvalue",
    });
    mockDisableMutateAsync.mockResolvedValue(undefined);
  });

  it("shows empty state when no keys exist", () => {
    renderPanel();
    expect(screen.getByText(/no api keys/i)).toBeInTheDocument();
  });

  it("creates a key and shows plain key once", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /create api key/i }));
    await user.type(screen.getByLabelText(/name/i), "path-graph-pipeline");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() => {
      expect(mockCreateMutateAsync).toHaveBeenCalledWith({
        name: "path-graph-pipeline",
        expires_in_days: null,
      });
    });

    expect(screen.getByText("ak_1_secretvalue")).toBeInTheDocument();
    expect(screen.getByText(/copy this key now/i)).toBeInTheDocument();
  });

  it("revokes a key after confirmation", async () => {
    mockUseMyApiKeys.mockReturnValue({
      data: {
        items: [
          {
            id: 5,
            name: "ci-bot",
            created_at: "2026-01-01T00:00:00Z",
            expires_at: null,
            disabled: false,
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    });

    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /^revoke$/i }));
    const revokeButtons = screen.getAllByRole("button", { name: /^revoke$/i });
    await user.click(revokeButtons[revokeButtons.length - 1]);

    await waitFor(() => {
      expect(mockDisableMutateAsync).toHaveBeenCalledWith(5);
    });
  });
});
