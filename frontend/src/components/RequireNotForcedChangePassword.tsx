import { Navigate, Outlet } from "react-router-dom";
import { useSession } from "../hooks/useSession";

export function RequireNotForcedChangePassword() {
  const { data: session, isLoading } = useSession();
  if (isLoading) return <div className="p-4">Loading...</div>;
  if (session?.must_change_password) return <Navigate to="/me" replace />;
  return <Outlet />;
}
