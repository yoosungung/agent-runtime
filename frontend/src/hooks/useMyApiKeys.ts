import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson } from "../lib/api";

export interface ApiKeyListItem {
  id: number;
  name: string;
  created_at: string;
  expires_at: string | null;
  disabled: boolean;
}

interface ApiKeyListResponse {
  items: ApiKeyListItem[];
  total: number;
}

interface ApiKeyCreateResponse {
  id: number;
  name: string;
  key: string;
}

export interface ApiKeyCreateInput {
  name: string;
  expires_in_days?: number | null;
}

export function useMyApiKeys() {
  return useQuery({
    queryKey: ["me", "api-keys"],
    queryFn: () => apiJson<ApiKeyListResponse>("/api/me/api-keys"),
  });
}

export function useCreateMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiKeyCreateInput) => {
      const payload: Record<string, unknown> = { name: body.name.trim() };
      if (body.expires_in_days != null) {
        payload.expires_in_days = body.expires_in_days;
      }
      return apiJson<ApiKeyCreateResponse>("/api/me/api-keys", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me", "api-keys"] }),
  });
}

export function useDisableMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: number) =>
      apiFetch(`/api/me/api-keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me", "api-keys"] }),
  });
}
