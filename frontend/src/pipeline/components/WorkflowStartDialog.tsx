import { useSourceWorkflowStatus } from "../hooks/usePipeline";

interface Props {
  open: boolean;
  sourceId: string;
  title: string;
  idleDescription: string;
  confirmLabel: string;
  isSubmitting?: boolean;
  showSyncMode?: boolean;
  syncMode?: "delta" | "full";
  onSyncModeChange?: (mode: "delta" | "full") => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export function WorkflowStartDialog({
  open,
  sourceId,
  title,
  idleDescription,
  confirmLabel,
  isSubmitting = false,
  showSyncMode = false,
  syncMode = "full",
  onSyncModeChange,
  onConfirm,
  onCancel,
}: Props) {
  const { data: status, isLoading, isError } = useSourceWorkflowStatus(sourceId, open);

  if (!open) return null;

  const active = status?.active ?? false;
  const argoAvailable = status?.argo_available ?? true;
  let description = idleDescription;
  if (isLoading) {
    description = "실행 중인 workflow가 있는지 확인하고 있습니다…";
  } else if (isError) {
    description =
      "workflow 상태를 확인하지 못했습니다. 그래도 시작하려면 확인을 누르세요.";
  } else if (active) {
    const wf = status?.workflow_name ?? "—";
    const phase = status?.phase ?? status?.last_run_status ?? "unknown";
    description = `이 source에 실행 중인 workflow가 있습니다 (${wf}, ${phase}). 중복으로 시작하면 두 작업이 동시에 실행됩니다. 그래도 시작하시겠습니까?`;
    if (!argoAvailable) {
      description +=
        " (Argo에 연결할 수 없어 DB 기록만으로 판단했습니다.)";
    }
  } else if (!argoAvailable) {
    description = `${idleDescription} (Argo 상태는 확인하지 못했습니다.)`;
  }

  const busy = isLoading || isSubmitting;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 z-10">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">{title}</h2>
        {active && !isLoading && (
          <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Workflow가 아직 실행 중입니다.
          </div>
        )}
        <p className="text-sm text-gray-600 mb-6">{description}</p>
        {showSyncMode && onSyncModeChange && (
          <div className="mb-4 rounded border border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-700">
            <p className="font-medium text-gray-900 mb-2">Collect mode</p>
            <label className="flex items-center gap-2 mb-1">
              <input
                type="radio"
                name="run-sync-mode"
                checked={syncMode === "full"}
                onChange={() => onSyncModeChange("full")}
              />
              Full resync (entire folder)
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="run-sync-mode"
                checked={syncMode === "delta"}
                onChange={() => onSyncModeChange("delta")}
              />
              Delta (incremental, uses stored cursor)
            </label>
          </div>
        )}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="px-4 py-2 rounded text-white text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
          >
            {isSubmitting ? "Starting…" : active ? "Start anyway" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
