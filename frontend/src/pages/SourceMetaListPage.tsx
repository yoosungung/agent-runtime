import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useSourceMetaList } from "../hooks/useSourceMeta";
import { Paginator } from "../components/Paginator";
import { usePagination } from "../hooks/usePagination";

interface Props {
  kind: "agent" | "mcp";
}

function formatChecksum(checksum: string | null): string {
  if (!checksum) return "-";
  return checksum.replace("sha256:", "").slice(0, 8);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function SourceMetaListPage({ kind }: Props) {
  const navigate = useNavigate();
  const { limit, offset, setOffset, reset } = usePagination(50);
  const [nameFilter, setNameFilter] = useState("");
  const [debouncedName, setDebouncedName] = useState("");
  const [retiredFilter, setRetiredFilter] = useState<boolean | undefined>(
    undefined,
  );

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedName(nameFilter);
      reset();
    }, 300);
    return () => clearTimeout(t);
  }, [nameFilter, reset]);

  const { data, isLoading, isError } = useSourceMetaList({
    kind,
    name: debouncedName || undefined,
    retired: retiredFilter,
    limit,
    offset,
  });

  const basePath = kind === "agent" ? "/agents" : "/mcp-servers";
  const title = kind === "agent" ? "Agents" : "MCP Servers";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
        <button
          onClick={() => navigate(`${basePath}/new`)}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium"
        >
          + New
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4 mb-4 flex gap-4 items-end flex-wrap">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Name prefix</label>
          <input
            type="text"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            placeholder="Filter by name..."
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Retired</label>
          <select
            value={
              retiredFilter === undefined
                ? ""
                : retiredFilter
                  ? "true"
                  : "false"
            }
            onChange={(e) => {
              const v = e.target.value;
              setRetiredFilter(v === "" ? undefined : v === "true");
              reset();
            }}
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="false">Active</option>
            <option value="true">Retired</option>
          </select>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading && (
          <p className="p-4 text-sm text-gray-500">Loading...</p>
        )}
        {isError && (
          <p className="p-4 text-sm text-red-500">Failed to load data.</p>
        )}
        {!isLoading && !isError && (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Name
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Version
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Runtime Pool
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Checksum
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Created
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Mode
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {data?.items.length === 0 && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-4 py-8 text-sm text-gray-500 text-center"
                      >
                        No {title.toLowerCase()} found.
                      </td>
                    </tr>
                  )}
                  {data?.items.map((item) => (
                    <tr
                      key={item.id}
                      onClick={() => navigate(`${basePath}/${item.id}`)}
                      className="hover:bg-gray-50 cursor-pointer"
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        {item.name}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {item.version}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {item.runtime_pool}
                      </td>
                      <td className="px-4 py-3 text-sm font-mono text-gray-500">
                        {formatChecksum(item.checksum)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(item.created_at)}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {item.deploy_mode === "image" ? (
                          <span className="bg-purple-100 text-purple-800 text-xs font-medium px-2 py-0.5 rounded">
                            image
                          </span>
                        ) : (
                          <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-0.5 rounded">
                            bundle
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {item.retired ? (
                          <span className="bg-red-100 text-red-800 text-xs font-medium px-2 py-0.5 rounded">
                            Retired
                          </span>
                        ) : (
                          <span className="bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5 rounded">
                            Active
                          </span>
                        )}
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
          </>
        )}
      </div>
    </div>
  );
}
