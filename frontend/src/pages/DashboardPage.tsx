import { Link } from "react-router-dom";
import { useSession } from "../hooks/useSession";

export function DashboardPage() {
  const { data: session } = useSession();

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">
        Welcome to agents-runtime admin console
      </h1>
      <p className="text-gray-600 mb-8">
        Logged in as{" "}
        <span className="font-medium">{session?.username}</span>
        {session?.tenant && (
          <> (tenant: <span className="font-medium">{session.tenant}</span>)</>
        )}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <Link
          to="/agents"
          className="bg-white shadow rounded-lg p-6 hover:shadow-md transition-shadow"
        >
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Agents</h2>
          <p className="text-sm text-gray-500">
            Manage agent source bundles, versions, and runtime config.
          </p>
        </Link>
        <Link
          to="/mcp-servers"
          className="bg-white shadow rounded-lg p-6 hover:shadow-md transition-shadow"
        >
          <h2 className="text-lg font-semibold text-gray-900 mb-1">
            MCP Servers
          </h2>
          <p className="text-sm text-gray-500">
            Manage MCP server source bundles and configurations.
          </p>
        </Link>
        <Link
          to="/users"
          className="bg-white shadow rounded-lg p-6 hover:shadow-md transition-shadow"
        >
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Users</h2>
          <p className="text-sm text-gray-500">
            Manage user accounts, passwords, and resource access.
          </p>
        </Link>
      </div>
    </div>
  );
}
