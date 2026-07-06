import { useNavigate } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Paginator } from "../components/Paginator";
import { useViewportPagination } from "../hooks/useViewportPagination";
import { useVfsWikiProjects } from "../hooks/useVfs";
import { formatVfsSize } from "../lib/vfsPaths";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function VfsWikiProjectsListPage() {
  const navigate = useNavigate();
  const { anchorRef, limit, offset, setOffset } = useViewportPagination({ min: 10 });
  const { data, isLoading, isError } = useVfsWikiProjects({ limit, offset });
  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="Wiki" />
      <p className="mb-4 text-sm text-gray-600">
        GraphRAG pipeline wiki pages per Knowledge project (
        <code className="text-xs bg-gray-100 px-1 rounded">vfs_wiki_files</code>).
      </p>
      <div ref={anchorRef} className="overflow-x-auto rounded border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2">Project</th>
              <th className="px-3 py-2">VFS mount</th>
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
                  Failed to load projects
                </td>
              </tr>
            )}
            {!isLoading &&
              !isError &&
              items.map((row) => (
                <tr
                  key={row.project_id}
                  className="cursor-pointer border-t hover:bg-gray-50"
                  onClick={() => navigate(`/vfs/wiki/${row.project_id}`)}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium">{row.name}</div>
                    <div className="text-xs text-gray-500">{row.slug}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{row.vfs_mount}</td>
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
