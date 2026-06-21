import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMyAccessResources } from "../hooks/useMyUserMeta";

type TabKind = "agent" | "mcp";

const TAB_ORDER: TabKind[] = ["agent", "mcp"];

interface Props {
  embedded?: boolean;
}

export function MyIntegrationsPanel({ embedded = false }: Props) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKind>("agent");
  const { data, isLoading, isError } = useMyAccessResources(tab);
  const configurableItems = (data?.items ?? []).filter(
    (item) => item.user_meta_required,
  );

  return (
    <div>
      {!embedded && (
        <>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">My Integrations</h1>
          <p className="text-sm text-gray-500 mb-6">
            Configure per-user settings for agents and MCP servers that require them.
          </p>
        </>
      )}

      {embedded && (
        <div className="mb-4">
          <h2 className="text-base font-semibold text-gray-900">Integrations</h2>
          <p className="text-sm text-gray-500 mt-1">
            Configure per-user settings for agents and MCP servers that require them.
          </p>
        </div>
      )}

      <div className="flex gap-4 border-b border-gray-200 mb-4">
        {TAB_ORDER.map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => setTab(kind)}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              tab === kind
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {kind === "mcp" ? "MCP" : "Agent"}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {isError && (
        <p className="text-sm text-red-600">Failed to load accessible resources.</p>
      )}

      {!isLoading && !isError && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
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
                  Status
                </th>
                <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Description
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {configurableItems.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-sm text-gray-500 text-center">
                    No {tab === "mcp" ? "MCP servers" : "agents"} require your settings.
                  </td>
                </tr>
              )}
              {configurableItems.map((item) => (
                <tr key={`${item.kind}-${item.name}`} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm">
                    <button
                      type="button"
                      onClick={() =>
                        navigate(
                          `/me/user-meta/${item.kind}/${encodeURIComponent(item.name)}`,
                        )
                      }
                      className="text-blue-600 hover:underline font-medium"
                    >
                      {item.name}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.version}</td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded ${
                        item.has_user_meta
                          ? "bg-green-100 text-green-800"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {item.has_user_meta ? "Configured" : "Not configured"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {item.template_description ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
