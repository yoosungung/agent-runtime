import { Navigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { data: session, isLoading, isError } = useSession();
  if (isLoading) return <div className="p-4">Loading...</div>;
  if (isError || !session) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
