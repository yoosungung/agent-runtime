import { Link, Outlet, useNavigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { apiJson } from "../lib/api";
import { queryClient } from "../lib/queryClient";

export function Layout() {
  const { data: session } = useSession();
  const navigate = useNavigate();

  async function handleLogout() {
    try {
      await apiJson("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore errors
    }
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-6">
              <Link
                to="/"
                className="font-semibold text-lg tracking-tight hover:text-gray-300"
              >
                agents-runtime
              </Link>
              {session?.is_admin && (
                <>
                  <Link
                    to="/agents"
                    className="text-sm hover:text-gray-300 transition-colors"
                  >
                    Agents
                  </Link>
                  <Link
                    to="/mcp-servers"
                    className="text-sm hover:text-gray-300 transition-colors"
                  >
                    MCP Servers
                  </Link>
                  <Link
                    to="/users"
                    className="text-sm hover:text-gray-300 transition-colors"
                  >
                    Users
                  </Link>
                  <Link
                    to="/audit"
                    className="text-sm hover:text-gray-300 transition-colors"
                  >
                    Audit
                  </Link>
                </>
              )}
            </div>
            <div className="flex items-center gap-4">
              <Link
                to="/chat"
                className="text-sm hover:text-gray-300 transition-colors"
              >
                Chat
              </Link>
              <Link
                to="/me"
                className="text-sm hover:text-gray-300 transition-colors"
              >
                {session?.username ?? "My Profile"}
              </Link>
              <button
                onClick={handleLogout}
                className="text-sm bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Outlet />
      </main>
    </div>
  );
}
