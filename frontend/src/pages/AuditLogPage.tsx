import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson, type PageResponse } from "../lib/api";
import { Paginator } from "../components/Paginator";
import { usePagination } from "../hooks/usePagination";

interface AuditLogEntry {
  id: number;
  action: string;
  actor_id: number;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
}

function buildQuery(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") {
      q.set(k, String(v));
    }
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

function actionBadgeClass(action: string): string {
  if (action.startsWith("user.delete") || action.startsWith("source_meta.delete")) {
    return "bg-red-100 text-red-800";
  }
  if (action.startsWith("access.revoke") || action.includes("retire")) {
    return "bg-amber-100 text-amber-800";
  }
  if (action.startsWith("user.create") || action.startsWith("source_meta.create") || action.startsWith("access.grant")) {
    return "bg-green-100 text-green-800";
  }
  return "bg-gray-100 text-gray-700";
}

export function AuditLogPage() {
  const { limit, offset, setOffset, reset } = usePagination(50);
  const [actorFilter, setActorFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["audit", { actor: actorFilter, action: actionFilter, limit, offset }],
    queryFn: () =>
      apiJson<PageResponse<AuditLogEntry>>(
        `/api/audit${buildQuery({
          actor_id: actorFilter || undefined,
          action: actionFilter || undefined,
          limit,
          offset,
        })}`,
      ),
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
      </div>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4 mb-4 flex gap-4 items-end flex-wrap">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Actor ID</label>
          <input
            type="number"
            value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); reset(); }}
            placeholder="User ID..."
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-28"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Action prefix</label>
          <input
            type="text"
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); reset(); }}
            placeholder="e.g. user. or access."
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          />
        </div>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading && <p className="p-4 text-sm text-gray-500">Loading...</p>}
        {isError && <p className="p-4 text-sm text-red-500">Failed to load audit log.</p>}
        {!isLoading && !isError && (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actor</th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {data?.items.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-gray-500">
                        No audit log entries.
                      </td>
                    </tr>
                  )}
                  {data?.items.map((entry) => (
                    <tr key={entry.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {formatDate(entry.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded ${actionBadgeClass(entry.action)}`}>
                          {entry.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-900">
                        <span className="font-medium">{entry.actor}</span>
                        <span className="text-gray-400 ml-1 text-xs">#{entry.actor_id}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs max-w-xs truncate">
                        {Object.entries(entry.details).map(([k, v]) => (
                          <span key={k} className="mr-2">
                            <span className="text-gray-400">{k}:</span>
                            <span className="ml-0.5">{String(v)}</span>
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && (
              <div className="border-t border-gray-200 px-4">
                <Paginator total={data.total} limit={limit} offset={offset} onOffsetChange={setOffset} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
