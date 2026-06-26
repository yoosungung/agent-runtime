export function workflowStatusClass(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "succeeded") return "bg-green-100 text-green-800";
  if (normalized === "running") return "bg-blue-100 text-blue-800";
  if (normalized === "pending") return "bg-yellow-100 text-yellow-800";
  if (normalized === "failed" || normalized === "error") return "bg-red-100 text-red-800";
  if (normalized === "submitted") return "bg-slate-100 text-slate-700";
  if (normalized === "empty") return "bg-gray-100 text-gray-600";
  if (normalized === "skipped" || normalized === "omitted") return "bg-gray-100 text-gray-600";
  return "bg-gray-100 text-gray-700";
}

export function WorkflowStatusBadge({ status }: { status: string }) {
  const label = status.trim() || "—";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${workflowStatusClass(status)}`}
    >
      {label}
    </span>
  );
}
