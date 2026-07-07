import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { HermesAgentNewPage } from "../pages/HermesAgentNewPage";

vi.mock("../hooks/useMyUserMeta", () => ({
  useMyAccessResources: () => ({
    data: {
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
    },
    isLoading: false,
  }),
}));

vi.mock("../hooks/useSourceMeta", () => ({
  useCreateHermesAgent: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("../hooks/useLlmPresets", () => ({
  useLlmPresets: () => ({
    data: [],
    isLoading: false,
    isError: false,
  }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HermesAgentNewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HermesAgentNewPage", () => {
  it("renders Hermes agent form fields", () => {
    renderPage();
    expect(screen.getByText("New Hermes Agent")).toBeInTheDocument();
    expect(screen.getByText("Soul (SOUL.md)")).toBeInTheDocument();
    expect(screen.getByText("search-server")).toBeInTheDocument();
    expect(screen.getByText("/profile/SOUL.md")).toBeInTheDocument();
    expect(screen.getByText("LLM 모델")).toBeInTheDocument();
  });
});
