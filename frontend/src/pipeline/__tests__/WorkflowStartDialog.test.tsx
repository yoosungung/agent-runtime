import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { WorkflowStartDialog } from "../components/WorkflowStartDialog";

const SOURCE_ID = "22222222-2222-4222-8222-222222222222";

const useSourceWorkflowStatus = vi.fn();

vi.mock("../hooks/usePipeline", () => ({
  useSourceWorkflowStatus: (...args: unknown[]) => useSourceWorkflowStatus(...args),
}));

function renderDialog(overrides: Partial<Parameters<typeof WorkflowStartDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <WorkflowStartDialog
        open
        sourceId={SOURCE_ID}
        title="Index pending files to RAG?"
        idleDescription="pending 문서를 RAG ingest workflow로 처리합니다."
        confirmLabel="Start workflow"
        onConfirm={onConfirm}
        onCancel={onCancel}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { onConfirm, onCancel };
}

describe("WorkflowStartDialog", () => {
  it("shows idle confirmation when no active workflow", async () => {
    useSourceWorkflowStatus.mockReturnValue({
      data: { active: false, argo_available: false },
      isLoading: false,
      isError: false,
    });
    const { onConfirm } = renderDialog();

    expect(screen.getByText(/pending 문서를 RAG ingest/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start workflow" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("warns and offers Start anyway when workflow is active", async () => {
    useSourceWorkflowStatus.mockReturnValue({
      data: {
        active: true,
        workflow_name: "ingest-manual-docs-abc",
        phase: "Running",
        argo_available: true,
      },
      isLoading: false,
      isError: false,
    });
    const { onConfirm } = renderDialog();

    await waitFor(() => {
      expect(screen.getByText(/Workflow가 아직 실행 중입니다/)).toBeInTheDocument();
    });
    expect(screen.getByText(/ingest-manual-docs-abc/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start anyway" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
