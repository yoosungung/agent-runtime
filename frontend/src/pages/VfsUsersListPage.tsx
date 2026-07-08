import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Paginator } from "../components/Paginator";
import { PageHeader } from "../components/PageHeader";
import { useViewportPagination } from "../hooks/useViewportPagination";
import { useVfsUsers } from "../hooks/useVfs";
import { formatVfsSize } from "../lib/vfsPaths";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function VfsUsersListPage() {
  const navigate = useNavigate();
  const { anchorRef, limit, offset, setOffset, reset } = useViewportPagination({ min: 10 });
  const [nameFilter, setNameFilter] = useState("");
  const [debouncedName, setDebouncedName] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedName(nameFilter);
      reset();
    }, 300);
    return () => clearTimeout(t);
  }, [nameFilter, reset]);

  const { data, isLoading, isError } = useVfsUsers({
    name: debouncedName || undefined,
    limit,
    offset,
  });
  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="User" />
      <p className="mb-4 text-sm text-gray-600">
        사용자별 개인 VFS (<code className="text-xs bg-gray-100 px-1 rounded">/user/</code>
        ). 런타임에서 사용자 스코프 파일로 마운트됩니다.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-4 flex flex-col sm:flex-row gap-4 sm:items-end flex-wrap">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Username prefix</label>
          <input
            type="text"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            placeholder="Filter by username..."
            className="w-full sm:w-auto border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div ref={anchorRef} className="bg-white shadow rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Username
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Tenant
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Files
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Size
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Modified
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                    Loading…
                  </td>
                </tr>
              )}
              {isError && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-red-600">
                    Failed to load users
                  </td>
                </tr>
              )}
              {!isLoading && !isError && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                    No VFS users found
                  </td>
                </tr>
              )}
              {items.map((row) => (
                <tr
                  key={row.user_id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() =>
                    navigate(`/vfs/user/${row.user_id}`, { state: { username: row.username } })
                  }
                >
                  <td className="px-4 py-3 text-sm font-medium text-blue-700">{row.username}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{row.tenant}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{row.file_count}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatVfsSize(row.total_bytes)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatDate(row.last_modified)}
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
