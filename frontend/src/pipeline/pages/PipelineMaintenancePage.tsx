import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { usePipelineSources } from "../hooks/usePipeline";
import {
  useCleanupProject,
  useDeleteProject,
  useProjectDeadLetters,
  useProjectTombstones,
  usePurgeProject,
  usePurgeSource,
  useReconcileProject,
} from "../hooks/usePipelineDocuments";

export function PipelineMaintenancePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: sourcesData } = usePipelineSources(projectId);
  const { data: tombstonesData } = useProjectTombstones(projectId);
  const { data: deadLettersData } = useProjectDeadLetters(projectId);
  const reconcileMut = useReconcileProject(projectId ?? "");
  const cleanupMut = useCleanupProject(projectId ?? "");
  const purgeProjectMut = usePurgeProject(projectId ?? "");
  const deleteProjectMut = useDeleteProject(projectId ?? "");
  const [purgeSourceId, setPurgeSourceId] = useState("");
  const purgeSourceMut = usePurgeSource();
  const [report, setReport] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmPurgeProject, setConfirmPurgeProject] = useState(false);
  const [confirmDeleteProject, setConfirmDeleteProject] = useState(false);
  const [confirmPurgeSource, setConfirmPurgeSource] = useState(false);
  const [showTombstones, setShowTombstones] = useState(false);

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  const tombstones = tombstonesData?.items ?? [];
  const deadLetters = deadLettersData?.items ?? [];

  async function runReconcile() {
    setError(null);
    try {
      const res = await reconcileMut.mutateAsync();
      setReport(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reconcile failed");
    }
  }

  async function runCleanup(dryRun: boolean) {
    setError(null);
    try {
      const res = await cleanupMut.mutateAsync(dryRun);
      setReport(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cleanup failed");
    }
  }

  async function runPurgeProject() {
    setError(null);
    try {
      const res = await purgeProjectMut.mutateAsync("admin console");
      setReport(
        JSON.stringify(
          {
            status: "submitted",
            run_kind: res.run_kind,
            workflow_name: res.workflow_name,
            workflow_template: res.workflow_template,
          },
          null,
          2,
        ),
      );
      setConfirmPurgeProject(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Purge failed");
      setConfirmPurgeProject(false);
    }
  }

  async function runDeleteProject() {
    setError(null);
    try {
      const res = await deleteProjectMut.mutateAsync("admin console");
      setReport(
        JSON.stringify(
          {
            status: "submitted",
            run_kind: res.run_kind,
            workflow_name: res.workflow_name,
            workflow_template: res.workflow_template,
          },
          null,
          2,
        ),
      );
      setConfirmDeleteProject(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setConfirmDeleteProject(false);
    }
  }

  async function runPurgeSource() {
    if (!purgeSourceId) return;
    setError(null);
    try {
      const res = await purgeSourceMut.mutateAsync({
        sourceId: purgeSourceId,
        reason: "admin console",
      });
      setReport(JSON.stringify(res, null, 2));
      setConfirmPurgeSource(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Purge failed");
      setConfirmPurgeSource(false);
    }
  }

  return (
    <div>
      <p className="mb-4 text-sm text-gray-600">
        Maintenance는 일상 탭 밖의 운영 도구입니다. reconcile·cleanup은 안전하게
        먼저 dry-run을 권장합니다.
      </p>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {report && (
        <div className="mb-4">
          <pre className="bg-gray-50 border rounded p-4 text-xs overflow-x-auto max-w-3xl">
            {report}
          </pre>
          <p className="mt-2 text-sm text-gray-600">
            Argo workflow가 제출되었습니다. 진행 상황은{" "}
            <Link
              to={`/pipeline/projects/${projectId}/runs`}
              className="text-blue-600 hover:underline"
            >
              Runs
            </Link>
            탭에서 확인하세요.
          </p>
        </div>
      )}

      <div className="mb-6">
        <h3 className="text-sm font-medium text-gray-900 mb-2">Lifecycle summary</h3>
        <ul className="text-sm text-gray-700 space-y-1">
          <li>
            Dead letters:{" "}
            <span className="font-medium">{deadLetters.length}</span>
            {deadLetters.length > 0 && (
              <>
                {" "}
                —{" "}
                <Link
                  to={`/pipeline/projects/${projectId}/documents?ingest_state=dead_letter`}
                  className="text-blue-600 hover:underline"
                >
                  Documents에서 보기
                </Link>
              </>
            )}
          </li>
          <li>
            Tombstones:{" "}
            <span className="font-medium">{tombstones.length}</span>
            {tombstones.length > 0 && (
              <button
                type="button"
                onClick={() => setShowTombstones((v) => !v)}
                className="ml-2 text-blue-600 hover:underline text-sm"
              >
                {showTombstones ? "숨기기" : "목록 보기"}
              </button>
            )}
          </li>
        </ul>
        {showTombstones && tombstones.length > 0 && (
          <div className="mt-3 border border-gray-200 rounded overflow-hidden max-w-xl max-h-48 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-2 py-1 text-left">Hash</th>
                  <th className="px-2 py-1 text-left">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {tombstones.map((row, i) => (
                  <tr key={`${row.content_hash ?? i}`}>
                    <td className="px-2 py-1 font-mono">
                      {String(row.content_hash ?? "—").slice(0, 16)}…
                    </td>
                    <td className="px-2 py-1">{String(row.reason ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <section className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Index reconcile</h3>
          <p className="text-sm text-gray-600 mb-3">
            PG(pgvector)·Nebula 간 고아 인덱스를 정리합니다.
          </p>
          <button
            type="button"
            onClick={runReconcile}
            disabled={reconcileMut.isPending}
            className="text-sm bg-blue-600 text-white rounded px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50"
          >
            {reconcileMut.isPending ? "Running…" : "Run reconcile"}
          </button>
        </section>

        <section className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Artifact cleanup</h3>
          <p className="text-sm text-gray-600 mb-3">미사용 S3 artifact 정리.</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => runCleanup(true)}
              disabled={cleanupMut.isPending}
              className="text-sm border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
            >
              Dry run
            </button>
            <button
              type="button"
              onClick={() => runCleanup(false)}
              disabled={cleanupMut.isPending}
              className="text-sm border border-orange-200 text-orange-800 rounded px-3 py-1.5 hover:bg-orange-50"
            >
              Execute cleanup
            </button>
          </div>
        </section>

        <section className="bg-white shadow rounded-lg p-4 border border-red-100">
          <h3 className="text-sm font-medium text-red-900 mb-2">Danger zone</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Purge source</label>
              <div className="flex gap-2">
                <select
                  value={purgeSourceId}
                  onChange={(e) => setPurgeSourceId(e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm flex-1"
                >
                  <option value="">Select source…</option>
                  {(sourcesData?.items ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={!purgeSourceId}
                  onClick={() => setConfirmPurgeSource(true)}
                  className="text-sm text-red-700 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50 disabled:opacity-50"
                >
                  Purge source
                </button>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setConfirmPurgeProject(true)}
              className="text-sm text-red-700 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50"
            >
              Purge entire project
            </button>
            <button
              type="button"
              onClick={() => setConfirmDeleteProject(true)}
              disabled={deleteProjectMut.isPending}
              className="text-sm text-white bg-red-700 border border-red-800 rounded px-3 py-1.5 hover:bg-red-800 disabled:opacity-50"
            >
              Delete project
            </button>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={confirmDeleteProject}
        title="Delete project?"
        description="Purge entire project와 동일한 blob·인덱스 정리 후 PG 행까지 Argo workflow로 영구 삭제합니다. 완료 후 프로젝트 목록에서 사라집니다."
        confirmLabel="Delete project"
        destructive
        onConfirm={runDeleteProject}
        onCancel={() => setConfirmDeleteProject(false)}
      />

      <ConfirmDialog
        open={confirmPurgeProject}
        title="Purge project?"
        description="프로젝트 내 문서·인덱스·raw를 Argo workflow로 삭제합니다. 완료까지 시간이 걸릴 수 있으며 Runs에서 진행을 확인합니다."
        confirmLabel="Purge project"
        destructive
        onConfirm={runPurgeProject}
        onCancel={() => setConfirmPurgeProject(false)}
      />

      <ConfirmDialog
        open={confirmPurgeSource}
        title="Purge source?"
        description="선택한 source의 모든 문서가 purge됩니다."
        confirmLabel="Purge source"
        destructive
        onConfirm={runPurgeSource}
        onCancel={() => setConfirmPurgeSource(false)}
      />
    </div>
  );
}
