import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Paginator } from "../../components/Paginator";
import { useViewportPagination } from "../../hooks/useViewportPagination";
import { WorkflowStartedBanner, type WorkflowStartedInfo } from "../components/WorkflowStartedBanner";
import { WorkflowStatusBadge } from "../components/WorkflowStatusBadge";
import {
  type PipelineRun,
  usePipelineRuns,
  useSubmitProjectGraphrag,
} from "../hooks/usePipeline";

const ACTIVE_GRAPHRAG_STATUSES = new Set(["Running", "Pending", "submitted"]);

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function runKindLabel(run: PipelineRun): string {
  return run.run_kind === "graphrag" ? "graphrag" : "ingest";
}

function buildActiveGraphragByBatch(runs: PipelineRun[]): Map<string, boolean> {
  const active = new Map<string, boolean>();
  for (const run of runs) {
    if (run.run_kind !== "graphrag" || !run.batch_id) continue;
    if (ACTIVE_GRAPHRAG_STATUSES.has(run.status)) {
      active.set(run.batch_id, true);
    }
  }
  return active;
}

function hasGraphragSucceededForBatch(runs: PipelineRun[], batchId: string): boolean {
  return runs.some(
    (r) =>
      r.run_kind === "graphrag" && r.batch_id === batchId && r.status === "Succeeded",
  );
}

export function PipelineRunsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { anchorRef, limit, offset, setOffset } = useViewportPagination({ min: 10 });
  const runsQuery = usePipelineRuns(projectId, { limit, offset });
  const graphragMut = useSubmitProjectGraphrag(projectId ?? "");
  const runs = runsQuery.data?.items ?? [];
  const recentDocs = runsQuery.data?.recent_documents ?? [];
  const argoAvailable = runsQuery.data?.argo_available ?? true;

  const activeGraphragByBatch = useMemo(
    () => buildActiveGraphragByBatch(runs),
    [runs],
  );

  const [confirmBatchId, setConfirmBatchId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [workflowStarted, setWorkflowStarted] = useState<WorkflowStartedInfo | null>(
    null,
  );

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  async function confirmGraphrag() {
    if (!confirmBatchId) return;
    setActionError(null);
    try {
      const res = await graphragMut.mutateAsync(confirmBatchId);
      setWorkflowStarted({
        batchId: res.batch_id,
        workflowName: res.workflow_name || "—",
        fileCount: res.document_count,
        actionLabel: "Graph & Wiki 빌드",
      });
      setConfirmBatchId(null);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "GraphRAG submit failed");
      setConfirmBatchId(null);
    }
  }

  const rebuild =
    confirmBatchId !== null && hasGraphragSucceededForBatch(runs, confirmBatchId);

  return (
    <div>
      <p className="mb-4 text-sm text-gray-600">
        RAG ingest가 Succeeded인 batch에서 Graph & Wiki를 빌드할 수 있습니다. 필요 시
        재실행(멱등 upsert)도 가능합니다.
      </p>

      {actionError && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {workflowStarted && (
        <WorkflowStartedBanner
          info={workflowStarted}
          runsHref={`/pipeline/projects/${projectId}/runs`}
          onDismiss={() => setWorkflowStarted(null)}
        />
      )}

      <div className="space-y-6">
        {!argoAvailable && (
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
            Argo Workflows에 연결할 수 없어 제출 시점 status만 표시합니다.
          </p>
        )}
        <div ref={anchorRef} className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Kind</th>
                <th className="px-4 py-2 font-medium">Workflow</th>
                <th className="px-4 py-2 font-medium">Batch</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Ended</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                    No runs yet.
                  </td>
                </tr>
              ) : (
                runs.map((run) => {
                  const isIngestSucceeded =
                    (run.run_kind ?? "ingest") === "ingest" && run.status === "Succeeded";
                  const graphragActive = Boolean(
                    run.batch_id && activeGraphragByBatch.get(run.batch_id),
                  );
                  const canBuild =
                    isIngestSucceeded && run.batch_id && !graphragActive;

                  return (
                    <tr key={run.id}>
                      <td className="px-4 py-2 text-gray-700">{runKindLabel(run)}</td>
                      <td className="px-4 py-2 font-mono text-xs">{run.workflow_name}</td>
                      <td className="px-4 py-2 font-mono text-xs">{run.batch_id}</td>
                      <td className="px-4 py-2">
                        <WorkflowStatusBadge status={run.status} />
                      </td>
                      <td className="px-4 py-2 text-gray-600">
                        {formatDate(run.started_at)}
                      </td>
                      <td className="px-4 py-2 text-gray-600">
                        {formatDate(run.ended_at)}
                      </td>
                      <td className="px-4 py-2">
                        {isIngestSucceeded && graphragActive && (
                          <span className="text-xs text-amber-700">GraphRAG 실행 중…</span>
                        )}
                        {canBuild && (
                          <button
                            type="button"
                            onClick={() => setConfirmBatchId(run.batch_id!)}
                            disabled={graphragMut.isPending}
                            className="text-xs bg-blue-600 hover:bg-blue-700 text-white rounded px-2 py-1 disabled:opacity-50"
                          >
                            Graph & Wiki 빌드
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
          {runsQuery.data && (
            <div className="border-t border-gray-200 px-4">
              <Paginator
                total={runsQuery.data.total}
                limit={limit}
                offset={offset}
                onOffsetChange={setOffset}
              />
            </div>
          )}
        </div>

        <div>
          <h2 className="text-sm font-medium text-gray-900 mb-2">Recent documents</h2>
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {recentDocs.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-4 py-6 text-center text-gray-500">
                      No documents indexed yet.
                    </td>
                  </tr>
                ) : (
                  recentDocs.map((doc) => (
                    <tr key={doc.document_id}>
                      <td className="px-4 py-2 font-mono text-xs">{doc.source_id}</td>
                      <td className="px-4 py-2">{doc.ingest_state}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmBatchId !== null}
        title={rebuild ? "Graph & Wiki 재빌드?" : "Graph & Wiki 빌드?"}
        description={
          rebuild
            ? `batch ${confirmBatchId}의 Graph/Wiki를 다시 생성합니다. 기존 Nebula·S3 wiki는 멱등 upsert로 덮어씁니다.`
            : `batch ${confirmBatchId}의 indexed RAG chunks로 Graph(Nebula)와 Wiki(S3)를 생성합니다.`
        }
        confirmLabel={graphragMut.isPending ? "Starting…" : "Start workflow"}
        onConfirm={confirmGraphrag}
        onCancel={() => setConfirmBatchId(null)}
      />
    </div>
  );
}
