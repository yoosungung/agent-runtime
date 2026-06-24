import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import {
  useDeletePipelineSource,
  usePipelineSource,
  useRunPipelineSource,
  useTestPipelineSource,
  useUpdatePipelineSource,
} from "../hooks/usePipeline";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function PipelineSourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: source, isLoading, isError } = usePipelineSource(id);
  const updateMut = useUpdatePipelineSource(id ?? "");
  const deleteMut = useDeletePipelineSource();
  const testMut = useTestPipelineSource(id ?? "");
  const runMut = useRunPipelineSource(id ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!id) {
    return <p className="text-sm text-red-600">Missing source id.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !source) {
    return <p className="text-sm text-red-600">Source not found.</p>;
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
        `Found ${res.file_count} file(s)` +
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
        </div>

        <div>
          <span className="text-gray-500 block mb-1">Config</span>
          <pre className="bg-gray-50 rounded p-3 text-xs overflow-auto">
            {JSON.stringify(source.config, null, 2)}
          </pre>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
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

      {testResult && (
        <p className="text-sm text-green-700 mb-2">{testResult}</p>
      )}
      {runResult && (
        <p className="text-sm text-green-700 mb-2">{runResult}</p>
      )}

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
