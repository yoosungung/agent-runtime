import { useParams } from "react-router-dom";
import { WorkflowStatusBadge } from "../components/WorkflowStatusBadge";
import { usePipelineRuns } from "../hooks/usePipeline";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function PipelineRunsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const runsQuery = usePipelineRuns(projectId);
  const runs = runsQuery.data?.runs ?? [];
  const recentDocs = runsQuery.data?.recent_documents ?? [];
  const argoAvailable = runsQuery.data?.argo_available ?? true;

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <div className="space-y-6">
        {!argoAvailable && (
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
            Argo Workflows에 연결할 수 없어 제출 시점 status만 표시합니다.
          </p>
        )}
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Workflow</th>
                <th className="px-4 py-2 font-medium">Batch</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Ended</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                    No runs yet.
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <tr key={run.id}>
                    <td className="px-4 py-2 font-mono text-xs">{run.workflow_name}</td>
                    <td className="px-4 py-2 font-mono text-xs">{run.batch_id}</td>
                    <td className="px-4 py-2">
                      <WorkflowStatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-2 text-gray-600">{formatDate(run.started_at)}</td>
                    <td className="px-4 py-2 text-gray-600">{formatDate(run.ended_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
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
    </div>
  );
}
