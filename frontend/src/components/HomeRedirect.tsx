import { Navigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { isAdminRole, isDeveloperRole } from "../lib/roles";
import { DashboardPage } from "../pages/DashboardPage";

export function HomeRedirect() {
  const { data: session, isLoading } = useSession();
  if (isLoading) {
    return <div className="p-4">Loading...</div>;
  }
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  if (isAdminRole(session.role)) {
    return <DashboardPage />;
  }
  if (isDeveloperRole(session.role)) {
    return <Navigate to="/bundle/agents" replace />;
  }
  return <Navigate to="/agents" replace />;
}
