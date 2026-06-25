import { Link, useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { IngestStateBadge } from "../../knowledge/components/IngestStateBadge";
import { usePipelineProject } from "../../pipeline/hooks/usePipeline";
import { useProjectDeadLetters } from "../hooks/useFiles";

export function FilesDeadLettersPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data: project } = usePipelineProject(projectId);
  const { data, isLoading, isError } = useProjectDeadLetters(projectId);
  const items = data?.items ?? [];

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <PageHeader title={project ? `${project.name} — Dead letters` : "Dead letters"} />
      <p className="mb-4 text-sm text-gray-600">parse 실패로 격리된 문서입니다.</p>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load.</p>}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                    No dead-letter documents.
                  </td>
                </tr>
              ) : (
                items.map((doc) => (
                  <tr
                    key={doc.document_id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() =>
                      navigate(
                        `/files/projects/${projectId}/documents/${doc.document_id}`,
                      )
                    }
                  >
                    <td className="px-4 py-2 font-mono text-xs">{doc.source_id}</td>
                    <td className="px-4 py-2 font-mono text-xs">{doc.document_id}</td>
                    <td className="px-4 py-2">
                      <IngestStateBadge state={doc.ingest_state} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs">
        <Link
          to={`/files/projects/${projectId}/documents?ingest_state=dead_letter`}
          className="text-blue-600 hover:underline"
        >
          Documents 필터로 보기
        </Link>
      </p>
    </div>
  );
}
