import { Link } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import {
  useDashboardSummary,
  type ResourceStatusCounts,
  type PoolRuntimeStatus,
  type RecentIssue,
} from "../hooks/useDashboardSummary";
import { sourceMetaDetailPath } from "../lib/sourceMetaPaths";

function StatusPill({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "green" | "yellow" | "red" | "gray";
}) {
  const colors = {
    green: "bg-green-100 text-green-800",
    yellow: "bg-yellow-100 text-yellow-800",
    red: "bg-red-100 text-red-800",
    gray: "bg-gray-100 text-gray-700",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full ${colors[tone]}`}
    >
      <span>{count}</span>
      <span>{label}</span>
    </span>
  );
}

function ResourceStatusPanel({
  title,
  counts,
  detailPath,
}: {
  title: string;
  counts: ResourceStatusCounts;
  detailPath: string;
}) {
  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <p className="text-sm text-gray-500 mt-1">{counts.total} registered</p>
        </div>
        <Link
          to={detailPath}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium shrink-0"
        >
          View all
        </Link>
      </div>
      <div className="flex flex-wrap gap-2">
        <StatusPill label="active" count={counts.active} tone="green" />
        <StatusPill label="pending" count={counts.pending} tone="yellow" />
        <StatusPill label="failed" count={counts.failed} tone="red" />
        <StatusPill label="retired" count={counts.retired} tone="gray" />
      </div>
    </div>
  );
}

function PoolTable({
  title,
  pools,
}: {
  title: string;
  pools: PoolRuntimeStatus[];
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{title}</h3>
      {pools.length === 0 ? (
        <p className="text-sm text-gray-500">No warm pods registered.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-500">
                <th className="pb-2 pr-4 font-medium">Runtime</th>
                <th className="pb-2 pr-4 font-medium">Pods</th>
                <th className="pb-2 pr-4 font-medium">Active</th>
                <th className="pb-2 font-medium">Capacity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {pools.map((pool) => (
                <tr key={pool.runtime_kind}>
                  <td className="py-2 pr-4 font-mono text-gray-900">
                    {pool.runtime_kind}
                  </td>
                  <td className="py-2 pr-4 text-gray-700">{pool.pod_count}</td>
                  <td className="py-2 pr-4 text-gray-700">
                    {pool.active_requests}
                  </td>
                  <td className="py-2 text-gray-700">{pool.max_capacity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RecentIssuesList({ issues }: { issues: RecentIssue[] }) {
  if (issues.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No pending or failed deployments right now.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-gray-100">
      {issues.map((issue) => (
        <li key={issue.id} className="py-3 first:pt-0 last:pb-0">
          <Link
            to={sourceMetaDetailPath(issue)}
            className="flex items-center justify-between gap-4 hover:text-blue-700"
          >
            <div>
              <p className="text-sm font-medium text-gray-900">
                {issue.name}
                <span className="text-gray-500 font-normal">@{issue.version}</span>
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {issue.kind} · {issue.deploy_mode}
              </p>
            </div>
            <span
              className={`text-xs font-medium px-2 py-0.5 rounded ${
                issue.status === "failed"
                  ? "bg-red-100 text-red-800"
                  : "bg-yellow-100 text-yellow-800"
              }`}
            >
              {issue.status}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function DashboardPage() {
  const { data: session } = useSession();
  const { data: summary, isLoading, isError } = useDashboardSummary();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          Dashboard
        </h1>
        <p className="text-gray-600">
          Logged in as{" "}
          <span className="font-medium">{session?.username}</span>
          {session?.tenant && (
            <>
              {" "}
              (tenant: <span className="font-medium">{session.tenant}</span>)
            </>
          )}
        </p>
      </div>

      <section>
        <div className="flex items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Status Monitoring</h2>
          {summary && (
            <span className="text-xs text-gray-500">Auto-refreshes every 30s</span>
          )}
        </div>

        {isLoading && (
          <p className="text-sm text-gray-500">Loading status...</p>
        )}
        {isError && (
          <p className="text-sm text-red-500">Failed to load dashboard status.</p>
        )}

        {summary && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ResourceStatusPanel
                title="Agent Resources"
                counts={summary.resources.agent}
                detailPath="/agents"
              />
              <ResourceStatusPanel
                title="MCP Resources"
                counts={summary.resources.mcp}
                detailPath="/bundle/mcp"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-white shadow rounded-lg p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Runtime Pools
                </h2>
                {!summary.pools.available && summary.pools.error && (
                  <p className="text-sm text-amber-700 bg-amber-50 border border-amber-100 rounded px-3 py-2 mb-4">
                    Pool metrics unavailable: {summary.pools.error}
                  </p>
                )}
                <div className="space-y-6">
                  <PoolTable title="Agent pools" pools={summary.pools.agents} />
                  <PoolTable title="MCP pools" pools={summary.pools.mcp} />
                </div>
              </div>

              <div className="bg-white shadow rounded-lg p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Recent Issues
                </h2>
                <RecentIssuesList issues={summary.recent_issues} />
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
