import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { PipelineSourcesListPage } from "../pages/PipelineSourcesListPage";

vi.mock("../hooks/usePipeline", () => ({
  usePipelineSources: vi.fn(() => ({
    data: {
      items: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          tenant: "dev",
          name: "kms",
          driver: "sharepoint",
          source_id: "sharepoint:kms",
          config: {},
          enabled: true,
          schedule_cron: null,
          last_batch_id: null,
          last_run_at: null,
          last_run_status: null,
          created_at: null,
          updated_at: null,
        },
      ],
    },
    isLoading: false,
    isError: false,
  })),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PipelineSourcesListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PipelineSourcesListPage", () => {
  it("renders source list", () => {
    renderPage();
    expect(screen.getByText("Pipeline Sources")).toBeInTheDocument();
    expect(screen.getByText("kms")).toBeInTheDocument();
    expect(screen.getByText("sharepoint")).toBeInTheDocument();
  });
});
