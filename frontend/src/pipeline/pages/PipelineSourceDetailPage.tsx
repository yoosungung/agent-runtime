import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileDropZone } from "../../components/FileDropZone";
import { PageHeader } from "../../components/PageHeader";
import { MANUAL_DEFAULT_ALLOWED_EXTENSIONS } from "../lib/manualSourceDefaults";
import {
  useDeletePipelineSource,
  useIngestPipelineSource,
  usePipelineSource,
  usePipelineSourceDocuments,
  useRunPipelineSource,
  useTestPipelineSource,
  useUpdatePipelineSource,
  useUploadPipelineFiles,
} from "../hooks/usePipeline";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function ingestStateBadge(state: string): string {
  if (state === "pending") return "bg-yellow-100 text-yellow-800";
  if (state === "indexed_rag") return "bg-green-100 text-green-800";
  if (state === "dead_letter") return "bg-red-100 text-red-800";
  return "bg-gray-100 text-gray-700";
}

export function PipelineSourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: source, isLoading, isError } = usePipelineSource(id);
  const { data: documentsData, refetch: refetchDocuments } = usePipelineSourceDocuments(id);
  const updateMut = useUpdatePipelineSource(id ?? "");
  const deleteMut = useDeletePipelineSource();
  const testMut = useTestPipelineSource(id ?? "");
  const runMut = useRunPipelineSource(id ?? "");
  const uploadMut = useUploadPipelineFiles(id ?? "");
  const ingestMut = useIngestPipelineSource(id ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const [ingestResult, setIngestResult] = useState<string | null>(null);
  const [ingestAfterUpload, setIngestAfterUpload] = useState(false);
  const [scheduleCron, setScheduleCron] = useState("");
  const [scheduleSaved, setScheduleSaved] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const isManual = source?.driver === "manual";
  const documents = documentsData?.items ?? [];
  const pendingCount = documents.filter((d) => d.ingest_state === "pending").length;

  if (!id) {
    return <p className="text-sm text-red-600">Missing source id.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !source) {
    return <p className="text-sm text-red-600">Source not found.</p>;
  }

  const scheduleInput = scheduleCron || source.schedule_cron || "";

  async function saveSchedule() {
    setActionError(null);
    setScheduleSaved(null);
    try {
      const value = scheduleInput.trim();
      await updateMut.mutateAsync({ schedule_cron: value || null });
      setScheduleSaved(value ? `Schedule saved: ${value} (UTC)` : "Schedule removed");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Schedule update failed");
    }
  }

  async function toggleEnabled() {
    setActionError(null);
    try {
      await updateMut.mutateAsync({ enabled: !source!.enabled });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function handleTest() {
    setActionError(null);
    setTestResult(null);
    try {
      const res = await testMut.mutateAsync();
      setTestResult(
        isManual
          ? `${res.file_count} document(s) on record` +
              (res.sample_names.length ? `: ${res.sample_names.join(", ")}` : "")
          : `Found ${res.file_count} file(s)` +
              (res.sample_names.length ? `: ${res.sample_names.join(", ")}` : ""),
      );
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Test failed");
    }
  }

  async function handleRun() {
    setActionError(null);
    setRunResult(null);
    try {
      const res = await runMut.mutateAsync();
      if (res.file_count === 0) {
        setRunResult("No files collected — workflow not submitted.");
      } else {
        const files =
          res.file_count == null
            ? "collect + ingest"
            : `${res.file_count} file(s)`;
        setRunResult(
          `Submitted batch ${res.batch_id} (${files}) → workflow ${res.workflow_name || "—"}`,
        );
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Run failed");
    }
  }

  async function handleUpload(files: File[]) {
    setActionError(null);
    setUploadResult(null);
    try {
      const res = await uploadMut.mutateAsync(files);
      setUploadResult(
        `Uploaded ${res.uploaded_count}, skipped ${res.skipped_count}` +
          (res.items.some((i) => i.status === "rejected")
            ? ` (${res.items.filter((i) => i.status === "rejected").length} rejected)`
            : ""),
      );
      await refetchDocuments();
      if (ingestAfterUpload && res.uploaded_count > 0) {
        await handleIngest();
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function handleIngest() {
    setActionError(null);
    setIngestResult(null);
    try {
      const res = await ingestMut.mutateAsync([]);
      if (!res.file_count) {
        setIngestResult("No pending documents — workflow not submitted.");
      } else {
        setIngestResult(
          `Submitted batch ${res.batch_id} (${res.file_count} files) → workflow ${res.workflow_name || "—"}`,
        );
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Ingest failed");
    }
  }

  async function handleDelete() {
    if (!id) return;
    setActionError(null);
    try {
      await deleteMut.mutateAsync(id);
      navigate("/pipeline/sources");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const allowedExt =
    typeof source.config.allowed_extensions === "string" &&
    source.config.allowed_extensions.trim()
      ? source.config.allowed_extensions
      : MANUAL_DEFAULT_ALLOWED_EXTENSIONS;
  const maxMb =
    typeof source.config.max_file_mb === "number"
      ? source.config.max_file_mb
      : Number(source.config.max_file_mb ?? 100);

  return (
    <div>
      <div className="mb-4 text-sm">
        <Link to="/pipeline/sources" className="text-blue-600 hover:underline">
          Sources
        </Link>
        <span className="text-gray-400 mx-2">/</span>
        <span className="text-gray-900 font-medium">{source.name}</span>
      </div>

      <PageHeader title={source.name} />

      {actionError && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <div className="bg-white shadow rounded-lg p-6 mb-4 max-w-2xl space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-2">
          <span className="text-gray-500">Driver</span>
          <span>{source.driver}</span>
          <span className="text-gray-500">Source ID</span>
          <span className="font-mono text-xs break-all">{source.source_id}</span>
          <span className="text-gray-500">Enabled</span>
          <span>{source.enabled ? "Yes" : "No"}</span>
          <span className="text-gray-500">Last run</span>
          <span>{formatDate(source.last_run_at)}</span>
          <span className="text-gray-500">Last status</span>
          <span>{source.last_run_status ?? "—"}</span>
          <span className="text-gray-500">Last batch</span>
          <span className="font-mono text-xs">{source.last_batch_id ?? "—"}</span>
          {!isManual && (
            <>
              <span className="text-gray-500">Schedule (UTC)</span>
              <span className="font-mono text-xs">{source.schedule_cron ?? "—"}</span>
            </>
          )}
        </div>

        <div>
          <span className="text-gray-500 block mb-1">Config</span>
          <pre className="bg-gray-50 rounded p-3 text-xs overflow-auto">
            {JSON.stringify(source.config, null, 2)}
          </pre>
        </div>
      </div>

      {!isManual && (
        <div className="bg-white shadow rounded-lg p-6 mb-4 max-w-2xl">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Scheduled collect</h3>
          <p className="text-xs text-gray-500 mb-3">
            5-field cron (minute hour day month weekday, UTC). 예:{" "}
            <code className="bg-gray-100 px-0.5 rounded">0 2 * * *</code> = 매일 02:00 UTC.
            비우면 CronWorkflow를 삭제합니다. Disable 시 스케줄은 유지되지만 일시 중지됩니다.
          </p>
          <div className="flex gap-2">
            <input
              value={scheduleInput}
              onChange={(e) => {
                setScheduleCron(e.target.value);
                setScheduleSaved(null);
              }}
              placeholder="0 2 * * *"
              className="border border-gray-300 rounded px-3 py-2 flex-1 font-mono text-sm"
            />
            <button
              type="button"
              onClick={saveSchedule}
              disabled={updateMut.isPending}
              className="text-sm border border-gray-300 rounded px-3 py-2 hover:bg-gray-50 disabled:opacity-50"
            >
              {updateMut.isPending ? "Saving…" : "Save schedule"}
            </button>
          </div>
          {scheduleSaved && (
            <p className="mt-2 text-sm text-green-700">{scheduleSaved}</p>
          )}
        </div>
      )}

      {isManual && (
        <div className="bg-white shadow rounded-lg p-6 mb-4 max-w-2xl">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Upload raw files</h3>
          <p className="text-xs text-gray-500 mb-3">
            Files are stored under{" "}
            <code className="bg-gray-100 px-0.5 rounded">raw/&#123;tenant&#125;/&#123;source_id&#125;/…</code>.
            Identical content (SHA-256) is skipped — S3 overwrite is not allowed.
          </p>
          <FileDropZone
            accept={allowedExt}
            maxMb={maxMb}
            multiple
            allowDirectories
            onFiles={handleUpload}
            label="Drag & drop files or folders, or click to select"
          />
          <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={ingestAfterUpload}
              onChange={(e) => setIngestAfterUpload(e.target.checked)}
            />
            Ingest pending documents after upload
          </label>
          {uploadMut.isPending && (
            <p className="mt-2 text-sm text-gray-500">Uploading…</p>
          )}
          {uploadResult && (
            <p className="mt-2 text-sm text-green-700">{uploadResult}</p>
          )}
        </div>
      )}

      {isManual && (
        <div className="bg-white shadow rounded-lg p-6 mb-4 max-w-3xl overflow-x-auto">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-900">Documents</h3>
            <span className="text-xs text-gray-500">{pendingCount} pending</span>
          </div>
          {documents.length === 0 ? (
            <p className="text-sm text-gray-500">No documents yet.</p>
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b">
                  <th className="py-2 pr-4">Filename</th>
                  <th className="py-2 pr-4">Hash</th>
                  <th className="py-2 pr-4">State</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.document_id} className="border-b border-gray-100">
                    <td className="py-2 pr-4 font-mono text-xs">{doc.filename}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-gray-600">
                      {doc.content_hash.slice(0, 8)}…
                    </td>
                    <td className="py-2 pr-4">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs ${ingestStateBadge(doc.ingest_state)}`}
                      >
                        {doc.ingest_state}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        {!isManual && (
          <>
            <button
              type="button"
              onClick={handleTest}
              disabled={testMut.isPending}
              className="text-sm border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50"
            >
              {testMut.isPending ? "Testing…" : "Test connection"}
            </button>
            <button
              type="button"
              onClick={handleRun}
              disabled={runMut.isPending || !source.enabled}
              className="text-sm bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 disabled:opacity-50"
            >
              {runMut.isPending ? "Running…" : "Run now"}
            </button>
          </>
        )}
        {isManual && (
          <>
            <button
              type="button"
              onClick={handleTest}
              disabled={testMut.isPending}
              className="text-sm border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50"
            >
              {testMut.isPending ? "Refreshing…" : "Refresh document count"}
            </button>
            <button
              type="button"
              onClick={handleIngest}
              disabled={ingestMut.isPending || !source.enabled || pendingCount === 0}
              className="text-sm bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 disabled:opacity-50"
            >
              {ingestMut.isPending ? "Submitting…" : "Ingest pending"}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={toggleEnabled}
          disabled={updateMut.isPending}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
        >
          {source.enabled ? "Disable" : "Enable"}
        </button>
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          className="text-sm text-red-600 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50"
        >
          Delete
        </button>
      </div>

      {testResult && <p className="text-sm text-green-700 mb-2">{testResult}</p>}
      {runResult && <p className="text-sm text-green-700 mb-2">{runResult}</p>}
      {ingestResult && <p className="text-sm text-green-700 mb-2">{ingestResult}</p>}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete source?"
        description={`Delete "${source.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
        destructive
      />
    </div>
  );
}
