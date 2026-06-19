import { Navigate, Outlet } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { roleAtLeast, type UserRole } from "../lib/roles";

interface Props {
  min: UserRole;
  redirectTo?: string;
}

export function RequireRole({ min, redirectTo = "/me" }: Props) {
  const { data: session, isLoading } = useSession();
  if (isLoading) return <div className="p-4">Loading...</div>;
  if (!session || !roleAtLeast(session.role, min)) {
    return <Navigate to={redirectTo} replace />;
  }
  return <Outlet />;
}
