import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeProjectProvider } from "../../knowledge/context/KnowledgeProjectContext";
import { PipelineSourcesListPage } from "../pages/PipelineSourcesListPage";

const PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000";

vi.mock("../hooks/usePipeline", () => ({
  usePipelineProject: vi.fn(() => ({
    data: {
      id: PROJECT_ID,
      name: "Default",
      slug: "default",
      tenant: "dev",
      created_at: null,
    },
    isLoading: false,
    isError: false,
  })),
  usePipelineSources: vi.fn(() => ({
    data: {
      items: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          tenant: "dev",
          project_id: PROJECT_ID,
          name: "kms",
          driver: "sharepoint",
          source_id: "sharepoint:kms",
          config: {},
          credential_id: null,
          enabled: true,
          schedule_cron: null,
          last_batch_id: null,
          last_run_at: null,
          last_run_status: null,
          created_at: null,
          updated_at: null,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    },
    isLoading: false,
    isError: false,
  })),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <KnowledgeProjectProvider>
        <MemoryRouter initialEntries={[`/pipeline/projects/${PROJECT_ID}/sources`]}>
          <Routes>
            <Route
              path="/pipeline/projects/:projectId/sources"
              element={<PipelineSourcesListPage />}
            />
          </Routes>
        </MemoryRouter>
      </KnowledgeProjectProvider>
    </QueryClientProvider>,
  );
}

describe("PipelineSourcesListPage", () => {
  it("renders source list under project", () => {
    renderPage();
    expect(screen.getByText("+ New Source")).toBeInTheDocument();
    expect(screen.getByText("kms")).toBeInTheDocument();
    expect(screen.getByText("sharepoint")).toBeInTheDocument();
  });
});
