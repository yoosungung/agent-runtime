import { useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { usePipelineProject, usePipelineRuns } from "../hooks/usePipeline";

export function PipelineRunsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = usePipelineProject(projectId);
  const runsQuery = usePipelineRuns(projectId);
  const runs = runsQuery.data?.runs ?? [];
  const recentDocs = runsQuery.data?.recent_documents ?? [];

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <PageHeader title={project ? `${project.name} — Runs` : "Pipeline Runs"} />

      <div className="space-y-6">
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Workflow</th>
                <th className="px-4 py-2 font-medium">Batch</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                    No runs yet.
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <tr key={run.id}>
                    <td className="px-4 py-2 font-mono text-xs">{run.workflow_name}</td>
                    <td className="px-4 py-2 font-mono text-xs">{run.batch_id}</td>
                    <td className="px-4 py-2">{run.status}</td>
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
