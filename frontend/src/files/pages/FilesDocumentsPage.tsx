import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { IngestStateBadge } from "../../knowledge/components/IngestStateBadge";
import { usePipelineProject } from "../../pipeline/hooks/usePipeline";
import { useProjectDocuments } from "../hooks/useFiles";

const STATES = ["", "pending", "indexed_rag", "dead_letter", "purging", "purged"];

export function FilesDocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { data: project } = usePipelineProject(projectId);
  const [ingestState, setIngestState] = useState(
    searchParams.get("ingest_state") ?? "",
  );
  const sourceFilter = searchParams.get("source_id") ?? "";

  const filters = useMemo(
    () => ({
      ingest_state: ingestState || undefined,
      source_id: sourceFilter || undefined,
    }),
    [ingestState, sourceFilter],
  );

  const { data, isLoading, isError } = useProjectDocuments(projectId, filters);
  const items = data?.items ?? [];

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <PageHeader title={project ? `${project.name} — Documents` : "Documents"} />

      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div>
          <label className="block text-xs text-gray-500 mb-1">ingest_state</label>
          <select
            value={ingestState}
            onChange={(e) => setIngestState(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm"
          >
            {STATES.map((s) => (
              <option key={s || "all"} value={s}>
                {s || "All"}
              </option>
            ))}
          </select>
        </div>
        {sourceFilter && (
          <p className="text-sm text-gray-600">
            Source filter: <code className="bg-gray-100 px-1 rounded">{sourceFilter}</code>
          </p>
        )}
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load documents.</p>}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Filename</th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Hash</th>
                <th className="px-4 py-2 font-medium">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                    No documents.
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
                    <td className="px-4 py-2 font-mono text-xs">{doc.filename}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">
                      {doc.source_id}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-500">
                      {doc.content_hash.slice(0, 12)}…
                    </td>
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

      <p className="mt-4 text-xs text-gray-500">
        <Link to={`/pipeline/projects/${projectId}/sources`} className="text-blue-600 hover:underline">
          Pipeline sources
        </Link>
      </p>
    </div>
  );
}
