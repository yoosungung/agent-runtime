import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { usePipelineProjects } from "../../pipeline/hooks/usePipeline";

export function FilesProjectsPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = usePipelineProjects();
  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="파일관리" />
      <p className="mb-4 text-sm text-gray-600">
        Knowledge Project별 문서 인벤토리·lifecycle(purge·tombstone·reconcile)을
        관리합니다. agent VFS(<Link to="/vfs" className="text-blue-600 hover:underline">/vfs</Link>
        )와는 별개입니다.
      </p>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load projects.</p>}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Project</th>
                <th className="px-4 py-2 font-medium">Slug</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={2} className="px-4 py-6 text-center text-gray-500">
                    No projects.{" "}
                    <Link to="/pipeline" className="text-blue-600 hover:underline">
                      Create a project in Pipeline
                    </Link>
                  </td>
                </tr>
              ) : (
                items.map((p) => (
                  <tr
                    key={p.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/files/projects/${p.id}/documents`)}
                  >
                    <td className="px-4 py-2 font-medium">{p.name}</td>
                    <td className="px-4 py-2 font-mono text-xs">{p.slug}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
