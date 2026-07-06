import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Paginator } from "../components/Paginator";
import { PageHeader } from "../components/PageHeader";
import { useViewportPagination } from "../hooks/useViewportPagination";
import { useVfsAgents } from "../hooks/useVfs";
import { generalVisibilityLabel } from "../lib/generalVisibility";
import { formatVfsSize, vfsAgentBrowserPath } from "../lib/vfsPaths";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function VfsAgentsListPage() {
  const navigate = useNavigate();
  const { anchorRef, limit, offset, setOffset, reset } = useViewportPagination({
    min: 10,
  });
  const [nameFilter, setNameFilter] = useState("");
  const [debouncedName, setDebouncedName] = useState("");
  const [includeRetired, setIncludeRetired] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedName(nameFilter);
      reset();
    }, 300);
    return () => clearTimeout(t);
  }, [nameFilter, reset]);

  useEffect(() => {
    reset();
  }, [includeRetired, reset]);

  const { data, isLoading, isError } = useVfsAgents({
    name: debouncedName || undefined,
    include_retired: includeRetired,
    limit,
    offset,
  });

  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="Agent" />

      <p className="mb-4 text-sm text-gray-600">
        General agent의 공유 영역 <code className="text-xs bg-gray-100 px-1 rounded">/agent/</code>
        를 관리합니다. VFS는 agent name 기준으로 공유되며 버전별로 분리되지 않습니다.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-4 flex flex-col sm:flex-row gap-4 sm:items-end flex-wrap">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Name prefix</label>
          <input
            type="text"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            placeholder="Filter by name..."
            className="w-full sm:w-auto border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={includeRetired}
            onChange={(e) => setIncludeRetired(e.target.checked)}
          />
          Include retired
        </label>
      </div>

      <div ref={anchorRef} className="bg-white shadow rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Visibility</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">VFS</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Files</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Size</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Modified</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    Loading…
                  </td>
                </tr>
              )}
              {isError && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-red-600">
                    Failed to load agents
                  </td>
                </tr>
              )}
              {!isLoading && !isError && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    No general agents found
                  </td>
                </tr>
              )}
              {items.map((item) => (
                <tr
                  key={`${item.kind}/${item.name}`}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(vfsAgentBrowserPath(item.kind, item.name))}
                >
                  <td className="px-4 py-3 text-sm font-medium text-blue-700">
                    {item.name}
                    {item.retired && (
                      <span className="ml-2 text-xs text-red-600 font-normal">retired</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.version}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {generalVisibilityLabel(item.visibility)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {item.vfs_enabled ? "enabled" : "disabled"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.file_count}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatVfsSize(item.total_bytes)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatDate(item.last_modified)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && (
          <div className="border-t border-gray-200 px-4">
            <Paginator
              total={data.total}
              limit={limit}
              offset={offset}
              onOffsetChange={setOffset}
            />
          </div>
        )}
      </div>
    </div>
  );
}
