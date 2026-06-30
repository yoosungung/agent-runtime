import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useSourceMetaList } from "../hooks/useSourceMeta";
import { Paginator } from "../components/Paginator";
import { useViewportPagination } from "../hooks/useViewportPagination";
import { sourceMetaDetailPath } from "../lib/sourceMetaPaths";
import { generalVisibilityLabel } from "../lib/generalVisibility";
import { PageHeader } from "../components/PageHeader";
import { ChatSelectableBadge } from "../components/ChatSelectableBadge";
import { listNewButtonLabel } from "../lib/uiLabels";

interface Props {
  kind: "agent" | "mcp";
  deployMode: "general" | "bundle";
  embedded?: boolean;
}

function formatChecksum(checksum: string | null): string {
  if (!checksum) return "-";
  return checksum.replace("sha256:", "").slice(0, 8);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function SourceMetaListPage({ kind, deployMode, embedded = false }: Props) {
  const navigate = useNavigate();
  const { anchorRef, limit, offset, setOffset, reset } = useViewportPagination({
    min: 10,
  });
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
    deploy_mode: deployMode,
    name: debouncedName || undefined,
    retired: retiredFilter,
    limit,
    offset,
  });

  const newPath =
    deployMode === "general"
      ? "/agents/new/general"
      : kind === "agent"
        ? "/bundle/agents/new"
        : "/bundle/mcp/new";
  const title =
    deployMode === "general"
      ? "Agent"
      : kind === "agent"
        ? "Bundle Agents"
        : "Bundle MCP";
  const emptyLabel =
    deployMode === "general"
      ? "agents"
      : kind === "agent"
        ? "bundle agents"
        : "bundle MCP servers";
  const showChatable = kind === "agent";
  const tableColSpan =
    deployMode === "general" ? 6 : showChatable ? 7 : 6;

  return (
    <div>
      <PageHeader title={embedded ? undefined : title}>
        <button
          onClick={() => navigate(newPath)}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium w-full sm:w-auto"
        >
          {listNewButtonLabel(kind)}
        </button>
      </PageHeader>

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
            className="w-full sm:w-auto border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="false">Active</option>
            <option value="true">Retired</option>
          </select>
        </div>
      </div>

      <div ref={anchorRef} className="bg-white shadow rounded-lg overflow-hidden">
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
                    {deployMode === "general" ? (
                      <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        사용 권한
                      </th>
                    ) : (
                      <>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Runtime Pool
                        </th>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Checksum
                        </th>
                      </>
                    )}
                    {showChatable && (
                      <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Chatable
                      </th>
                    )}
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Created
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
                        colSpan={tableColSpan}
                        className="px-4 py-8 text-sm text-gray-500 text-center"
                      >
                        No {emptyLabel} found.
                      </td>
                    </tr>
                  )}
                  {data?.items.map((item) => (
                    <tr
                      key={item.id}
                      onClick={() =>
                        navigate(sourceMetaDetailPath(item))
                      }
                      className="hover:bg-gray-50 cursor-pointer"
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        {item.name}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {item.version}
                      </td>
                      {deployMode === "general" ? (
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {generalVisibilityLabel(item.visibility)}
                        </td>
                      ) : (
                        <>
                          <td className="px-4 py-3 text-sm text-gray-600">
                            {item.runtime_pool}
                          </td>
                          <td className="px-4 py-3 text-sm font-mono text-gray-500">
                            {formatChecksum(item.checksum)}
                          </td>
                        </>
                      )}
                      {showChatable && (
                        <td className="px-4 py-3 text-sm">
                          <ChatSelectableBadge selectable={item.chat_selectable} />
                        </td>
                      )}
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(item.created_at)}
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
