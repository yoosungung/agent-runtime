import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { UserSearchInput } from "../components/UserSearchInput";

const mockUseUsersList = vi.fn();

vi.mock("../hooks/useUsers", () => ({
  useUsersList: (...args: unknown[]) => mockUseUsersList(...args),
}));

function renderInput(onSelect = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onSelect,
    ...render(
      <QueryClientProvider client={qc}>
        <UserSearchInput onSelect={onSelect} placeholder="Add user by username..." />
      </QueryClientProvider>,
    ),
  };
}

describe("UserSearchInput", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUsersList.mockReturnValue({
      data: {
        items: [
          { id: 1, username: "admin" },
          { id: 2, username: "user" },
        ],
        total: 2,
      },
      isFetching: false,
    });
  });

  it("disables browser autofill on the search field", () => {
    renderInput();
    const input = screen.getByRole("combobox", { name: "Add user by username..." });
    expect(input).toHaveAttribute("autocomplete", "off");
    expect(input).toHaveAttribute("type", "search");
  });

  it("shows browse list on focus before typing", async () => {
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByRole("combobox", { name: "Add user by username..." }));

    expect(mockUseUsersList).toHaveBeenCalledWith(
      { username: undefined, limit: 20, offset: 0 },
      { enabled: true },
    );
    expect(screen.getByRole("option", { name: "admin" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "user" })).toBeInTheDocument();
  });

  it("selects a user from the dropdown", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderInput(onSelect);

    await user.click(screen.getByRole("combobox", { name: "Add user by username..." }));
    await user.click(screen.getByRole("option", { name: "user" }));

    expect(onSelect).toHaveBeenCalledWith({ id: 2, username: "user" });
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("shows empty state when no users match", async () => {
    mockUseUsersList.mockReturnValue({
      data: { items: [], total: 0 },
      isFetching: false,
    });
    const user = userEvent.setup();
    renderInput();

    const input = screen.getByRole("combobox", { name: "Add user by username..." });
    await user.click(input);
    await user.type(input, "nobody");

    await waitFor(() => {
      expect(screen.getByText(/일치하는 사용자 없음/)).toBeInTheDocument();
    });
  });
});
