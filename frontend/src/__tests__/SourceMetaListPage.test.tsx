import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SourceMetaListPage } from "../pages/SourceMetaListPage";

const mockUseSourceMetaList = vi.fn();

vi.mock("../hooks/useSourceMeta", () => ({
  useSourceMetaList: (...args: unknown[]) => mockUseSourceMetaList(...args),
}));

vi.mock("../hooks/useViewportPagination", () => ({
  useViewportPagination: () => ({
    anchorRef: { current: null },
    limit: 10,
    offset: 0,
    setOffset: vi.fn(),
    reset: vi.fn(),
  }),
}));

function renderList(
  kind: "agent" | "mcp",
  deployMode: "general" | "bundle",
) {
  mockUseSourceMetaList.mockReturnValue({
    data: {
      items: [
        {
          id: 1,
          kind,
          name: "demo-agent",
          version: "v1",
          runtime_pool: "agent:compiled_graph",
          checksum: "sha256:abcdef0123456789",
          retired: false,
          deploy_mode: deployMode,
          visibility: "private",
          chat_selectable: false,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    },
    isLoading: false,
    isError: false,
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SourceMetaListPage kind={kind} deployMode={deployMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SourceMetaListPage", () => {
  it("shows Chatable before Created and Status on general agent list", () => {
    renderList("agent", "general");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Name",
      "Version",
      "사용 권한",
      "Chatable",
      "Created",
      "Status",
    ]);
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.queryByText("bundle")).not.toBeInTheDocument();
  });

  it("shows Chatable and omits Mode on bundle agent list", () => {
    renderList("agent", "bundle");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Name",
      "Version",
      "Runtime Pool",
      "Checksum",
      "Chatable",
      "Created",
      "Status",
    ]);
    expect(screen.queryByText("Mode")).not.toBeInTheDocument();
  });

  it("omits Chatable and Mode on bundle MCP list", () => {
    renderList("mcp", "bundle");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Name",
      "Version",
      "Runtime Pool",
      "Checksum",
      "Created",
      "Status",
    ]);
    expect(screen.queryByText("Chatable")).not.toBeInTheDocument();
    expect(screen.queryByText("Mode")).not.toBeInTheDocument();
  });
});
