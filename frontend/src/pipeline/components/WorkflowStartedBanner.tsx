import { Link } from "react-router-dom";

export interface WorkflowStartedInfo {
  batchId: string;
  workflowName: string;
  fileCount?: number | null;
  actionLabel: string;
}

interface Props {
  info: WorkflowStartedInfo;
  runsHref: string;
  onDismiss: () => void;
}

export function WorkflowStartedBanner({ info, runsHref, onDismiss }: Props) {
  const fileNote =
    info.fileCount == null
      ? ""
      : info.fileCount === 0
        ? " (처리할 파일 없음)"
        : ` (${info.fileCount} file(s))`;

  return (
    <div
      className="mb-4 rounded-lg border border-green-300 bg-green-50 px-4 py-4"
      role="status"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-green-900">{info.actionLabel} — workflow started</p>
          <p className="mt-1 text-sm text-green-800">
            Argo에 workflow가 제출되었습니다{fileNote}. Runs 탭에서 진행 상태를 확인하세요.
          </p>
          <dl className="mt-2 text-sm text-green-900 space-y-1">
            <div className="flex gap-2">
              <dt className="text-green-700 shrink-0">Batch</dt>
              <dd className="font-mono text-xs break-all">{info.batchId}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-green-700 shrink-0">Workflow</dt>
              <dd className="font-mono text-xs break-all">{info.workflowName}</dd>
            </div>
          </dl>
          <Link to={runsHref} className="mt-2 inline-block text-sm text-blue-700 hover:underline">
            Runs에서 확인 →
          </Link>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="text-sm text-green-800 hover:text-green-950"
          aria-label="Dismiss"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
