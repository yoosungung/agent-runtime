import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { GeneralAgentNewPage } from "../pages/GeneralAgentNewPage";

vi.mock("../hooks/useSourceMeta", () => ({
  useSourceMetaList: () => ({
    data: {
      items: [{ id: 1, name: "search-server", version: "v1" }],
      total: 1,
    },
    isLoading: false,
  }),
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
  });
});
