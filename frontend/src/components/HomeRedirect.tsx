import { Navigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { DashboardPage } from "../pages/DashboardPage";

export function HomeRedirect() {
  const { data: session, isLoading } = useSession();
  if (isLoading) {
    return <div className="p-4">Loading...</div>;
  }
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  return <DashboardPage />;
}
