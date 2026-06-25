import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { IngestStateBadge } from "../../knowledge/components/IngestStateBadge";
import {
  useDocument,
  usePurgeDocument,
  useReingestDocument,
  useRestoreDocument,
} from "../hooks/usePipelineDocuments";

export function PipelineDocumentDetailPage() {
  const { projectId, documentId } = useParams<{
    projectId: string;
    documentId: string;
  }>();
  const { data: doc, isLoading, isError } = useDocument(documentId);
  const purgeMut = usePurgeDocument(documentId ?? "");
  const restoreMut = useRestoreDocument(documentId ?? "");
  const reingestMut = useReingestDocument(documentId ?? "");
  const [confirmAction, setConfirmAction] = useState<
    "purge" | "restore" | "reingest" | null
  >(null);
  const [reason, setReason] = useState("");
  const [hardRaw, setHardRaw] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!projectId || !documentId) {
    return <p className="text-sm text-red-600">Missing ids.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !doc) {
    return <p className="text-sm text-red-600">Document not found.</p>;
  }

  async function runAction() {
    setError(null);
    setResult(null);
    try {
      if (confirmAction === "purge") {
        const res = await purgeMut.mutateAsync({
          reason: reason.trim() || undefined,
          hard_raw: hardRaw,
        });
        setResult(JSON.stringify(res));
      } else if (confirmAction === "restore") {
        const res = await restoreMut.mutateAsync();
        setResult(JSON.stringify(res));
      } else if (confirmAction === "reingest") {
        const res = await reingestMut.mutateAsync();
        setResult(JSON.stringify(res));
      }
      setConfirmAction(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
      setConfirmAction(null);
    }
  }

  const canPurge = !["purged", "purging"].includes(doc.ingest_state);
  const canRestore = doc.ingest_state === "purged";
  const canReingest = doc.ingest_state === "dead_letter";

  return (
    <div>
      <p className="mb-4 text-sm">
        <Link
          to={`/pipeline/projects/${projectId}/documents`}
          className="text-blue-600 hover:underline"
        >
          Documents
        </Link>
        <span className="text-gray-400 mx-2">/</span>
        <span className="font-mono text-xs">{doc.filename}</span>
      </p>

      <h2 className="text-lg font-semibold text-gray-900 mb-4 font-mono text-sm">
        {doc.filename}
      </h2>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {result && (
        <div className="mb-4 bg-green-50 border border-green-200 rounded px-4 py-3 text-sm text-green-800 font-mono text-xs break-all">
          {result}
        </div>
      )}

      <dl className="bg-white shadow rounded-lg p-4 text-sm space-y-3 mb-4 max-w-2xl">
        <div>
          <dt className="text-gray-500">State</dt>
          <dd>
            <IngestStateBadge state={doc.ingest_state} />
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Source</dt>
          <dd className="font-mono text-xs">{doc.source_id}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Content hash</dt>
          <dd className="font-mono text-xs break-all">{doc.content_hash}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Raw URI</dt>
          <dd className="font-mono text-xs break-all">{doc.s3_raw_uri}</dd>
        </div>
      </dl>

      {doc.dead_letter_error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 max-w-2xl">
          <h3 className="text-sm font-medium text-red-900 mb-2">Dead letter error</h3>
          <pre className="text-xs overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(doc.dead_letter_error, null, 2)}
          </pre>
        </div>
      )}

      <div className="flex flex-wrap gap-2 items-end mb-4">
        {canPurge && (
          <>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Purge reason (optional)"
              className="border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={hardRaw}
                onChange={(e) => setHardRaw(e.target.checked)}
              />
              hard_raw
            </label>
            <button
              type="button"
              onClick={() => setConfirmAction("purge")}
              className="text-sm border border-red-200 text-red-700 rounded px-3 py-1.5 hover:bg-red-50"
            >
              Purge
            </button>
          </>
        )}
        {canRestore && (
          <button
            type="button"
            onClick={() => setConfirmAction("restore")}
            className="text-sm border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
          >
            Restore
          </button>
        )}
        {canReingest && (
          <button
            type="button"
            onClick={() => setConfirmAction("reingest")}
            className="text-sm bg-blue-600 text-white rounded px-3 py-1.5 hover:bg-blue-700"
          >
            Re-ingest
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirmAction === "purge"}
        title="Purge document?"
        description="인덱스·파생물을 삭제합니다. tombstone이 설정될 수 있습니다."
        confirmLabel="Purge"
        onConfirm={runAction}
        onCancel={() => setConfirmAction(null)}
        destructive
      />

      <ConfirmDialog
        open={confirmAction === "restore"}
        title="Restore document?"
        description="Tombstone을 해제하고 ingest_state를 pending으로 되돌립니다."
        confirmLabel="Restore"
        onConfirm={runAction}
        onCancel={() => setConfirmAction(null)}
      />

      <ConfirmDialog
        open={confirmAction === "reingest"}
        title="Re-ingest document?"
        description="기존 인덱스를 compensation한 뒤 pending으로 둡니다."
        confirmLabel="Re-ingest"
        onConfirm={runAction}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
