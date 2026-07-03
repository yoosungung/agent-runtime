import { Link, useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { useVfsWikiProjects } from "../../hooks/useVfs";
import {
  usePipelineProject,
  usePipelineProjectBinding,
  usePipelineSources,
} from "../hooks/usePipeline";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function PipelineProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading, isError } = usePipelineProject(projectId);
  const { data: binding } = usePipelineProjectBinding(projectId);
  const { data: wikiProjects } = useVfsWikiProjects({ limit: 200, offset: 0 });
  const wikiStats = wikiProjects?.items.find((row) => row.project_id === projectId);
  const { data: sourcesData } = usePipelineSources(projectId, { limit: 50, offset: 0 });
  const sourceCount = sourcesData?.total ?? 0;

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !project) {
    return <p className="text-sm text-red-600">Project not found.</p>;
  }

  return (
    <div>
      <PageHeader title={project.name}>
        <button
          type="button"
          onClick={() => navigate(`/pipeline/projects/${projectId}/sources/new`)}
          className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded"
        >
          + New Source
        </button>
      </PageHeader>

      <p className="mb-4 text-sm text-gray-600 font-mono">{project.slug}</p>

      <div className="grid gap-4 md:grid-cols-2 mb-6">
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Sources</h3>
          <p className="text-2xl font-semibold text-gray-900">{sourceCount}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Documents</h3>
          <Link
            to={`/files/projects/${projectId}/documents`}
            className="text-sm text-blue-600 hover:underline"
          >
            파일관리에서 보기
          </Link>
        </div>
      </div>

      {binding && (
        <div className="bg-white shadow rounded-lg p-4 mb-6">
          <h3 className="text-sm font-medium text-gray-900 mb-3">Knowledge binding</h3>
          <dl className="text-sm space-y-2">
            <div>
              <dt className="text-gray-500">Index namespace</dt>
              <dd className="font-mono text-xs">{binding.rag.index_namespace}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Nebula space</dt>
              <dd className="font-mono text-xs">{binding.graph.nebula_space}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Wiki mount</dt>
              <dd className="font-mono text-xs">{binding.wiki.vfs_mount}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Wiki files</dt>
              <dd className="text-xs">
                {wikiStats ? (
                  <>
                    {wikiStats.file_count} file(s)
                    {wikiStats.file_count > 0 ? (
                      <>
                        {" "}
                        ·{" "}
                        <Link
                          to={`/vfs/wiki/${projectId}`}
                          className="text-blue-600 hover:underline"
                        >
                          VFS에서 보기
                        </Link>
                      </>
                    ) : null}
                  </>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-gray-500">
            RAG ingest 완료 후 Runs 탭에서 Graph & Wiki를 빌드할 수 있습니다 (재실행 가능).
          </p>
        </div>
      )}

      <div className="mt-8">
        <h3 className="text-sm font-medium text-gray-900 mb-3">Sources</h3>
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Driver</th>
                <th className="px-4 py-2 font-medium">Enabled</th>
                <th className="px-4 py-2 font-medium">Schedule</th>
                <th className="px-4 py-2 font-medium">Last run</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sourcesData?.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                    No sources yet.{" "}
                    <Link
                      to={`/pipeline/projects/${projectId}/sources/new`}
                      className="text-blue-600 hover:underline"
                    >
                      Create one
                    </Link>
                  </td>
                </tr>
              ) : (
                sourcesData?.items.map((src) => (
                  <tr
                    key={src.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() =>
                      navigate(`/pipeline/projects/${projectId}/sources/${src.id}`)
                    }
                  >
                    <td className="px-4 py-2 font-medium text-gray-900">{src.name}</td>
                    <td className="px-4 py-2 text-gray-700">{src.driver}</td>
                    <td className="px-4 py-2">{src.enabled ? "Yes" : "No"}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">
                      {src.schedule_cron ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {formatDate(src.last_run_at)}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {src.last_run_status ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

