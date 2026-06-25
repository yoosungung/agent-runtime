import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { PipelineDocumentsPage } from "../pages/PipelineDocumentsPage";

const PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000";

const docs = [
  {
    document_id: "doc-1",
    source_id: "manual:a",
    content_hash: "sha256:aaa",
    ingest_state: "indexed_rag",
    s3_raw_uri: "s3://b/a.pdf",
    filename: "report.pdf",
  },
  {
    document_id: "doc-2",
    source_id: "manual:b",
    content_hash: "sha256:bbb",
    ingest_state: "dead_letter",
    s3_raw_uri: "s3://b/b.pdf",
    filename: "broken.pdf",
  },
  {
    document_id: "doc-3",
    source_id: "manual:c",
    content_hash: "sha256:ccc",
    ingest_state: "purged",
    s3_raw_uri: "s3://b/c.pdf",
    filename: "old-report.pdf",
  },
];

vi.mock("../hooks/usePipeline", () => ({
  usePipelineProject: vi.fn(() => ({
    data: { id: PROJECT_ID, name: "Default", slug: "default" },
    isLoading: false,
    isError: false,
  })),
}));

vi.mock("../hooks/usePipelineDocuments", () => ({
  useProjectDocuments: vi.fn(() => ({
    data: { items: docs },
    isLoading: false,
    isError: false,
  })),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter
        initialEntries={[`/pipeline/projects/${PROJECT_ID}/documents`]}
      >
        <Routes>
          <Route
            path="/pipeline/projects/:projectId/documents"
            element={<PipelineDocumentsPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PipelineDocumentsPage", () => {
  it("filters documents by filename and status", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("broken.pdf")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/filename/i), "report");
    await waitFor(() => {
      expect(screen.queryByText("broken.pdf")).not.toBeInTheDocument();
    });

    await user.clear(screen.getByLabelText(/filename/i));
    await user.selectOptions(screen.getByLabelText(/status/i), "dead_letter");
    await waitFor(() => {
      expect(screen.getByText("broken.pdf")).toBeInTheDocument();
      expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText(/status/i), "purged");
    await waitFor(() => {
      expect(screen.getByText("old-report.pdf")).toBeInTheDocument();
      expect(screen.queryByText("broken.pdf")).not.toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText(/status/i), "indexed_rag");
    await waitFor(() => {
      expect(screen.getByText("report.pdf")).toBeInTheDocument();
      expect(screen.queryByText("broken.pdf")).not.toBeInTheDocument();
    });
  });
});
