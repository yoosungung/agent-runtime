import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { IngestStateBadge } from "../../knowledge/components/IngestStateBadge";
import { useProjectDocuments } from "../hooks/usePipelineDocuments";

const INGEST_STATE_FILTERS = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "indexed_rag", label: "Indexed (RAG)" },
  { value: "dead_letter", label: "Dead letter" },
  { value: "purging", label: "Purging" },
  { value: "purged", label: "Purged (tombstone)" },
] as const;

type DocStatusFilter = (typeof INGEST_STATE_FILTERS)[number]["value"];

const VALID_INGEST_STATES = new Set<Exclude<DocStatusFilter, "">>(
  INGEST_STATE_FILTERS.map((o) => o.value).filter((v): v is Exclude<DocStatusFilter, ""> => v !== ""),
);

function statusFromParams(value: string | null): DocStatusFilter {
  if (value === "tombstone") return "purged";
  if (value && VALID_INGEST_STATES.has(value as Exclude<DocStatusFilter, "">)) {
    return value as DocStatusFilter;
  }
  return "";
}

export function PipelineDocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [nameQuery, setNameQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<DocStatusFilter>(() =>
    statusFromParams(searchParams.get("ingest_state")),
  );
  const sourceFilter = searchParams.get("source_id") ?? "";

  const apiFilters = useMemo(
    () => ({
      ingest_state: statusFilter || undefined,
      source_id: sourceFilter || undefined,
    }),
    [statusFilter, sourceFilter],
  );

  const { data, isLoading, isError } = useProjectDocuments(projectId, apiFilters);
  const items = useMemo(() => {
    const all = data?.items ?? [];
    let filtered = all;
    if (statusFilter) {
      filtered = filtered.filter((d) => d.ingest_state === statusFilter);
    }
    const q = nameQuery.trim().toLowerCase();
    if (q) {
      filtered = filtered.filter((doc) => doc.filename.toLowerCase().includes(q));
    }
    return filtered;
  }, [data?.items, nameQuery, statusFilter]);

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div>
          <label htmlFor="doc-filename" className="block text-xs text-gray-500 mb-1">
            Filename
          </label>
          <input
            id="doc-filename"
            type="search"
            value={nameQuery}
            onChange={(e) => setNameQuery(e.target.value)}
            placeholder="contains…"
            className="border border-gray-300 rounded px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label htmlFor="doc-status" className="block text-xs text-gray-500 mb-1">
            Status
          </label>
          <select
            id="doc-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as DocStatusFilter)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm"
          >
            {INGEST_STATE_FILTERS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        {sourceFilter && (
          <p className="text-sm text-gray-600">
            Source: <code className="bg-gray-100 px-1 rounded">{sourceFilter}</code>
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
                        `/pipeline/projects/${projectId}/documents/${doc.document_id}`,
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
        Tombstone registry·reconcile·purge는{" "}
        <Link
          to={`/pipeline/projects/${projectId}/maintenance`}
          className="text-blue-600 hover:underline"
        >
          Maintenance
        </Link>
        에서 관리합니다.
      </p>
    </div>
  );
}
