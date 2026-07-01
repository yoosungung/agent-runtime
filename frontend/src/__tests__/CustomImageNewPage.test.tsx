import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { CustomImageNewPage } from "../pages/CustomImageNewPage";

vi.mock("../hooks/useCustomImages", () => ({
  useCreateCustomImage: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

function renderPage(kind: "agent" | "mcp" = "mcp") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CustomImageNewPage kind={kind} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CustomImageNewPage", () => {
  it("renders environment variables editor for container image", () => {
    renderPage("mcp");
    expect(screen.getByText("New MCP Image")).toBeInTheDocument();
    expect(screen.getByText(/Environment variables/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Add variable" })).toBeInTheDocument();
  });

  it("renders MCP knowledge policy checkbox for container MCP image", () => {
    renderPage("mcp");
    expect(
      screen.getByText("Pipeline project binding 필요 (general agent knowledge 경계)"),
    ).toBeInTheDocument();
  });

  it("shows chat selectable for agent image", () => {
    renderPage("agent");
    expect(screen.getByText(/Chat에서 선택 가능/)).toBeInTheDocument();
  });

  it("does not render MCP knowledge policy for agent image", () => {
    renderPage("agent");
    expect(
      screen.queryByText("Pipeline project binding 필요 (general agent knowledge 경계)"),
    ).not.toBeInTheDocument();
  });

  it.each(["agent", "mcp"] as const)(
    "adds environment variable row on %s new page",
    async (kind) => {
      const user = userEvent.setup();
      renderPage(kind);

      expect(screen.getAllByPlaceholderText("LOG_LEVEL")).toHaveLength(1);
      await user.click(screen.getByRole("button", { name: "+ Add variable" }));
      expect(screen.getAllByPlaceholderText("LOG_LEVEL")).toHaveLength(2);
    },
  );
});
