import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileDropZone } from "../../components/FileDropZone";
import { PageHeader } from "../../components/PageHeader";
import { MANUAL_DEFAULT_ALLOWED_EXTENSIONS } from "../lib/manualSourceDefaults";
import {
  WorkflowStartedBanner,
  type WorkflowStartedInfo,
} from "../components/WorkflowStartedBanner";
import { WorkflowStartDialog } from "../components/WorkflowStartDialog";
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

export function PipelineSourceDetailPage() {
  const { projectId, sourceId: id } = useParams<{ projectId: string; sourceId: string }>();
  const navigate = useNavigate();
  const { data: source, isLoading, isError } = usePipelineSource(id);
  const { data: documentsData, refetch: refetchDocuments } = usePipelineSourceDocuments(
    id,
    undefined,
    { limit: 1, offset: 0 },
  );
  const { data: pendingDocsData } = usePipelineSourceDocuments(
    id,
    "pending",
    { limit: 1, offset: 0 },
  );
  const updateMut = useUpdatePipelineSource(id ?? "");
  const deleteMut = useDeletePipelineSource();
  const testMut = useTestPipelineSource(id ?? "");
  const runMut = useRunPipelineSource(id ?? "");
  const uploadMut = useUploadPipelineFiles(id ?? "");
  const ingestMut = useIngestPipelineSource(id ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const [ingestAfterUpload, setIngestAfterUpload] = useState(false);
  const [scheduleCron, setScheduleCron] = useState("");
  const [scheduleSaved, setScheduleSaved] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingWorkflowAction, setPendingWorkflowAction] = useState<
    "run" | "ingest" | null
  >(null);
  const [workflowStarted, setWorkflowStarted] = useState<WorkflowStartedInfo | null>(
    null,
  );
  const [runSyncMode, setRunSyncMode] = useState<"delta" | "full">("full");
  const [configSyncModeDraft, setConfigSyncModeDraft] = useState<"delta" | "full" | null>(
    null,
  );
  const [syncSaved, setSyncSaved] = useState<string | null>(null);

  const isManual = source?.driver === "manual";
  const isSharePoint = source?.driver === "sharepoint";
  const documentCount = documentsData?.total ?? 0;
  const pendingCount = pendingDocsData?.total ?? 0;

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
  const storedSyncMode =
    source.config.sync_mode === "full" ? "full" : "delta";
  const deltaLink =
    typeof source.config.delta_link === "string" ? source.config.delta_link : "";
  const syncModeInput = configSyncModeDraft ?? storedSyncMode;

  async function saveSyncSettings() {
    if (!source) return;
    setActionError(null);
    setSyncSaved(null);
    try {
      const nextConfig = { ...source.config, sync_mode: syncModeInput };
      await updateMut.mutateAsync({ config: nextConfig });
      setSyncSaved(`Scheduled sync mode: ${syncModeInput}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Sync settings update failed");
    }
  }

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

  async function executeRun() {
    setActionError(null);
    setWorkflowStarted(null);
    try {
      const res = await runMut.mutateAsync({ sync_mode: runSyncMode });
      if (res.file_count === 0) {
        setActionError("No files collected — workflow not submitted.");
        return;
      }
      setWorkflowStarted({
        batchId: res.batch_id,
        workflowName: res.workflow_name || "—",
        fileCount: res.file_count,
        actionLabel: "Run now",
      });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Run failed");
      throw e;
    }
  }

  async function executeIngest() {
    setActionError(null);
    setWorkflowStarted(null);
    try {
      const res = await ingestMut.mutateAsync([]);
      if (!res.file_count) {
        setActionError("No pending documents — workflow not submitted.");
        return;
      }
      setWorkflowStarted({
        batchId: res.batch_id,
        workflowName: res.workflow_name || "—",
        fileCount: res.file_count,
        actionLabel: "Index to RAG",
      });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Ingest failed");
      throw e;
    }
  }

  async function confirmWorkflowStart() {
    try {
      if (pendingWorkflowAction === "run") {
        await executeRun();
      } else if (pendingWorkflowAction === "ingest") {
        await executeIngest();
      }
      setPendingWorkflowAction(null);
    } catch {
      // actionError already set; keep dialog open for retry
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
        await executeIngest();
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function handleDelete() {
    if (!id) return;
    setActionError(null);
    try {
      await deleteMut.mutateAsync(id);
      navigate(`/pipeline/projects/${projectId ?? source!.project_id}/sources`);
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

  const pid = projectId ?? source.project_id;

  return (
    <div>
      <div className="mb-4 text-sm">
        <Link
          to={`/pipeline/projects/${pid}/sources`}
          className="text-blue-600 hover:underline"
        >
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

      {workflowStarted && (
        <WorkflowStartedBanner
          info={workflowStarted}
          runsHref={`/pipeline/projects/${pid}/runs`}
          onDismiss={() => setWorkflowStarted(null)}
        />
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
          {isSharePoint && (
            <>
              <span className="text-gray-500">Scheduled sync</span>
              <span className="font-mono text-xs">{storedSyncMode}</span>
              <span className="text-gray-500">Delta cursor</span>
              <span className="text-xs">{deltaLink ? "configured" : "none"}</span>
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

      {isSharePoint && (
        <div className="bg-white shadow rounded-lg p-6 mb-4 max-w-2xl">
          <h3 className="text-sm font-medium text-gray-900 mb-2">SharePoint sync</h3>
          <p className="text-xs text-gray-500 mb-3">
            Cron 수집은 아래 모드를 사용합니다. Run now는 기본적으로 전체 재수집(full)이며,
            다이얼로그에서 delta를 선택할 수 있습니다. delta 성공 시 Graph delta 커서가
            자동 저장됩니다.
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <label className="text-sm text-gray-700" htmlFor="scheduled-sync-mode">
              Scheduled sync mode
            </label>
            <select
              id="scheduled-sync-mode"
              value={syncModeInput}
              onChange={(e) => {
                setConfigSyncModeDraft(e.target.value as "delta" | "full");
                setSyncSaved(null);
              }}
              className="border border-gray-300 rounded px-3 py-2 text-sm"
            >
              <option value="delta">delta (incremental)</option>
              <option value="full">full (entire folder)</option>
            </select>
            <button
              type="button"
              onClick={saveSyncSettings}
              disabled={updateMut.isPending}
              className="text-sm border border-gray-300 rounded px-3 py-2 hover:bg-gray-50 disabled:opacity-50"
            >
              {updateMut.isPending ? "Saving…" : "Save sync mode"}
            </button>
          </div>
          {syncSaved && <p className="text-sm text-green-700">{syncSaved}</p>}
          <p className="text-xs text-gray-500 mt-2">
            Delta cursor: {deltaLink ? "stored (hidden)" : "not set — next delta run starts fresh"}
          </p>
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

      <div className="bg-white shadow rounded-lg p-4 mb-4 max-w-xl">
        <h3 className="text-sm font-medium text-gray-900 mb-2">Documents</h3>
        <p className="text-sm text-gray-600">
          {documentCount} document(s)
          {pendingCount > 0 ? ` · ${pendingCount} pending ingest` : ""}
        </p>
        <Link
          to={`/pipeline/projects/${pid}/documents?source_id=${encodeURIComponent(source.source_id)}`}
          className="text-sm text-blue-600 hover:underline mt-2 inline-block"
        >
          Documents에서 보기
        </Link>
      </div>

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
              onClick={() => setPendingWorkflowAction("run")}
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
              onClick={() => setPendingWorkflowAction("ingest")}
              disabled={ingestMut.isPending || !source.enabled || pendingCount === 0}
              className="text-sm bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 disabled:opacity-50"
            >
              {ingestMut.isPending ? "Submitting…" : "Index to RAG"}
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

      <WorkflowStartDialog
        open={pendingWorkflowAction === "run"}
        sourceId={id}
        title="Run collect + ingest?"
        idleDescription="원격 source에서 파일을 수집하고 RAG ingest workflow를 시작합니다."
        confirmLabel="Start workflow"
        isSubmitting={runMut.isPending}
        showSyncMode={isSharePoint}
        syncMode={runSyncMode}
        onSyncModeChange={setRunSyncMode}
        onConfirm={confirmWorkflowStart}
        onCancel={() => setPendingWorkflowAction(null)}
      />
      <WorkflowStartDialog
        open={pendingWorkflowAction === "ingest"}
        sourceId={id}
        title="Index pending files to RAG?"
        idleDescription={`pending 상태 문서 ${pendingCount}개를 RAG ingest workflow로 처리합니다.`}
        confirmLabel="Start workflow"
        isSubmitting={ingestMut.isPending}
        onConfirm={confirmWorkflowStart}
        onCancel={() => setPendingWorkflowAction(null)}
      />

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
