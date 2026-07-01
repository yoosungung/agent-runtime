import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { GeneralAgentNewPage } from "../pages/GeneralAgentNewPage";

vi.mock("../hooks/useMyUserMeta", () => ({
  useMyAccessResources: (kind: string) => ({
    data:
      kind === "mcp"
        ? {
            items: [
              {
                kind: "mcp",
                name: "search-server",
                version: "v1",
                source_meta_id: 1,
                runtime_pool: "mcp:fastmcp",
                has_user_meta: false,
                user_meta_required: false,
                template_description: null,
                template_field_count: 0,
              },
            ],
            total: 1,
          }
        : { items: [], total: 0 },
    isLoading: false,
  }),
}));

vi.mock("../hooks/useSourceMeta", () => ({
  useCreateGeneralAgent: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <GeneralAgentNewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GeneralAgentNewPage", () => {
  it("renders general agent form fields", () => {
    renderPage();
    expect(screen.getByText("New Agent")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("search-server")).toBeInTheDocument();

    const versionInput = screen.getByLabelText("Version");
    const visibilitySelect = screen.getByLabelText("사용 권한");
    expect(versionInput.compareDocumentPosition(visibilitySelect)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(versionInput.closest(".grid")).toBe(visibilitySelect.closest(".grid"));
  });
});
