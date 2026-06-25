import { useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { usePipelineProject } from "../../pipeline/hooks/usePipeline";
import { useProjectTombstones } from "../hooks/useFiles";

export function FilesTombstonesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = usePipelineProject(projectId);
  const { data, isLoading, isError } = useProjectTombstones(projectId);
  const items = data?.items ?? [];

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <PageHeader title={project ? `${project.name} — Tombstones` : "Tombstones"} />
      <p className="mb-4 text-sm text-gray-600">
        삭제된 content_hash — 동일 hash 재업로드를 차단합니다.
      </p>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load tombstones.</p>}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Content hash</th>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                    No tombstones.
                  </td>
                </tr>
              ) : (
                items.map((row, i) => (
                  <tr key={`${row.content_hash ?? i}`}>
                    <td className="px-4 py-2 font-mono text-xs">
                      {String(row.content_hash ?? "—")}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {String(row.document_id ?? "—")}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {String(row.reason ?? "—")}
                    </td>
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
