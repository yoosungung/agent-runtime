import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { CustomImageListPage } from "../pages/CustomImageListPage";

vi.mock("../hooks/useCustomImages", () => ({
  useCustomImageList: () => ({
    data: [
      {
        id: 1,
        kind: "agent",
        name: "img-agent",
        version: "v1",
        slug: "img-agent-v1",
        image_uri: "ghcr.io/example/agent:v1",
        status: "active",
        chat_selectable: true,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useDeleteCustomImage: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRestartCustomImage: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function renderPage(kind: "agent" | "mcp") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CustomImageListPage kind={kind} embedded />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CustomImageListPage", () => {
  it("shows Chatable before Created and Status for container agents", () => {
    renderPage("agent");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Name",
      "Version",
      "Slug",
      "Image URI",
      "Chatable",
      "Created",
      "Status",
      "Actions",
    ]);
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("omits Chatable for container MCP list", () => {
    renderPage("mcp");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Name",
      "Version",
      "Slug",
      "Image URI",
      "Created",
      "Status",
      "Actions",
    ]);
    expect(screen.queryByText("Chatable")).not.toBeInTheDocument();
  });
});
