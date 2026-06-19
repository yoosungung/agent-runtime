import { Navigate, Outlet } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { isAdminRole } from "../lib/roles";

export function RequireAdmin() {
  const { data: session, isLoading } = useSession();
  if (isLoading) return <div className="p-4">Loading...</div>;
  if (!session || !isAdminRole(session.role)) return <Navigate to="/me" replace />;
  return <Outlet />;
}
