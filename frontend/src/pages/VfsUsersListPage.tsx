import { useNavigate } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Paginator } from "../components/Paginator";
import { useViewportPagination } from "../hooks/useViewportPagination";
import { useVfsUsers } from "../hooks/useVfs";
import { formatVfsSize } from "../lib/vfsPaths";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function VfsUsersListPage() {
  const navigate = useNavigate();
  const { anchorRef, limit, offset, setOffset } = useViewportPagination({ min: 10 });
  const { data, isLoading, isError } = useVfsUsers({ limit, offset });
  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="User" />
      <p className="mb-4 text-sm text-gray-600">
        사용자별 개인 VFS (<code className="text-xs bg-gray-100 px-1 rounded">vfs_user_files</code>
        ).
      </p>
      <div ref={anchorRef} className="overflow-x-auto rounded border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2">Username</th>
              <th className="px-3 py-2">Tenant</th>
              <th className="px-3 py-2">Files</th>
              <th className="px-3 py-2">Size</th>
              <th className="px-3 py-2">Modified</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {isError && (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-red-600">
                  Failed to load users
                </td>
              </tr>
            )}
            {!isLoading &&
              !isError &&
              items.map((row) => (
                <tr
                  key={row.user_id}
                  className="cursor-pointer border-t hover:bg-gray-50"
                  onClick={() => navigate(`/vfs/user/${row.user_id}`)}
                >
                  <td className="px-3 py-2 font-medium">{row.username}</td>
                  <td className="px-3 py-2">{row.tenant}</td>
                  <td className="px-3 py-2">{row.file_count}</td>
                  <td className="px-3 py-2">{formatVfsSize(row.total_bytes)}</td>
                  <td className="px-3 py-2">{formatDate(row.last_modified)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {data && (
        <Paginator total={data.total} limit={data.limit} offset={data.offset} onOffsetChange={setOffset} />
      )}
    </div>
  );
}
