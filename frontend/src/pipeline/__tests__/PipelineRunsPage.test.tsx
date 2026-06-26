import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { PipelineRunsPage } from "../pages/PipelineRunsPage";

const mockSubmit = vi.fn();
const mockRuns = vi.fn();

vi.mock("../hooks/usePipeline", () => ({
  usePipelineRuns: (...args: unknown[]) => mockRuns(...args),
  useSubmitProjectGraphrag: () => ({
    mutateAsync: mockSubmit,
    isPending: false,
  }),
}));

vi.mock("../../hooks/useViewportPagination", () => ({
  useViewportPagination: () => ({
    anchorRef: { current: null },
    limit: 25,
    offset: 0,
    setOffset: vi.fn(),
  }),
}));

describe("PipelineRunsPage", () => {
  it("shows Graph & Wiki build for succeeded ingest without active graphrag", () => {
    mockRuns.mockReturnValue({
      data: {
        items: [
          {
            id: "run-ingest",
            workflow_name: "ingest-src-abc",
            argo_uid: null,
            batch_id: "20260101-120000",
            status: "Succeeded",
            started_at: null,
            ended_at: null,
            run_kind: "ingest",
          },
        ],
        total: 1,
        argo_available: true,
      },
    });

    render(
      <MemoryRouter initialEntries={["/pipeline/projects/p1/runs"]}>
        <Routes>
          <Route path="/pipeline/projects/:projectId/runs" element={<PipelineRunsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: "Graph & Wiki 빌드" })).toBeInTheDocument();
  });

  it("hides build button when graphrag is active for batch", () => {
    mockRuns.mockReturnValue({
      data: {
        items: [
          {
            id: "run-ingest",
            workflow_name: "ingest-src-abc",
            argo_uid: null,
            batch_id: "20260101-120000",
            status: "Succeeded",
            started_at: null,
            ended_at: null,
            run_kind: "ingest",
          },
          {
            id: "run-gr",
            workflow_name: "graphrag-default-x",
            argo_uid: null,
            batch_id: "20260101-120000",
            status: "Running",
            started_at: null,
            ended_at: null,
            run_kind: "graphrag",
          },
        ],
        total: 2,
        argo_available: true,
      },
    });

    render(
      <MemoryRouter initialEntries={["/pipeline/projects/p1/runs"]}>
        <Routes>
          <Route path="/pipeline/projects/:projectId/runs" element={<PipelineRunsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByRole("button", { name: "Graph & Wiki 빌드" })).not.toBeInTheDocument();
    expect(screen.getByText("GraphRAG 실행 중…")).toBeInTheDocument();
  });
});
