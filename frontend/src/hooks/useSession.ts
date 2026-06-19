import { useQuery } from "@tanstack/react-query";
import { apiJson } from "../lib/api";
import type { UserRole } from "../lib/roles";

export interface Session {
  user_id: number;
  username: string;
  tenant: string | null;
  role: UserRole;
  must_change_password: boolean;
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => apiJson<Session>("/api/me"),
    retry: false,
    staleTime: 60_000,
  });
}
