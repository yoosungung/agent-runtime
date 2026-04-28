import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch, type PageResponse } from "../lib/api";

export interface User {
  id: number;
  username: string;
  tenant: string | null;
  is_admin: boolean;
  disabled: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface AccessEntry {
  kind: string;
  name: string;
  source_meta_id: number;
}

export interface UsersListParams {
  username?: string;
  tenant?: string;
  disabled?: boolean;
  limit?: number;
  offset?: number;
}

function buildQuery(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") {
      q.set(k, String(v));
    }
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function useUsersList(params: UsersListParams) {
  return useQuery({
    queryKey: ["users", "list", params],
    queryFn: () =>
      apiJson<PageResponse<User>>(
        `/api/users${buildQuery(params as Record<string, unknown>)}`,
      ),
  });
}

export function useUserById(id: number | undefined) {
  return useQuery({
    queryKey: ["users", id],
    queryFn: () => apiJson<User>(`/api/users/${id}`),
    enabled: id !== undefined,
  });
}

export function useUserAccess(
  id: number | undefined,
  params?: { limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: ["users", id, "access", params],
    queryFn: () =>
      apiJson<PageResponse<AccessEntry>>(
        `/api/users/${id}/access${buildQuery((params ?? {}) as Record<string, unknown>)}`,
      ),
    enabled: id !== undefined,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      username: string;
      password: string;
      tenant?: string;
      is_admin: boolean;
    }) =>
      apiJson<User>("/api/users", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", "list"] });
    },
  });
}

export function usePatchUser(id: number, updatedAt?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      data: Partial<Pick<User, "tenant" | "disabled" | "is_admin">>,
    ) => {
      const headers: Record<string, string> = {};
      if (updatedAt) {
        headers["If-Match"] = String(Math.floor(new Date(updatedAt).getTime() / 1000));
      }
      return apiJson<User>(`/api/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
        headers,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", id] });
      qc.invalidateQueries({ queryKey: ["users", "list"] });
    },
  });
}

export function useChangePassword(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { new_password: string }) =>
      apiJson<void>(`/api/users/${id}/password`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", id] });
    },
  });
}

export function useChangeSelfPassword() {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      apiJson<void>("/api/me/password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useDeleteUser(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch(`/api/users/${id}`, { method: "DELETE" }).then((r) => {
        if (!r.ok) return r.json().then((b) => Promise.reject(new Error(b?.detail ?? `HTTP ${r.status}`)));
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", "list"] });
    },
  });
}

export function useGrantAccess(userId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { kind: string; name: string }) =>
      apiFetch(`/api/users/${userId}/access`, {
        method: "POST",
        body: JSON.stringify(data),
      }).then((r) => {
        if (!r.ok && r.status !== 204)
          throw new Error(`HTTP ${r.status}`);
        return data;
      }),
    onSuccess: (_data) => {
      qc.invalidateQueries({ queryKey: ["users", userId, "access"] });
      // Also invalidate the source-meta access queries for this resource
      qc.invalidateQueries({
        queryKey: ["source-meta"],
        predicate: (q) =>
          q.queryKey.includes("access") &&
          q.queryKey.some((k) => typeof k === "string"),
      });
    },
  });
}

export function useRevokeAccess(userId: number, _sourceMetaId?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      kind: string;
      name: string;
      sourceMetaId?: number;
    }) =>
      apiFetch(
        `/api/users/${userId}/access?kind=${data.kind}&name=${data.name}`,
        { method: "DELETE" },
      ).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return data;
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["users", userId, "access"] });
      if (data.sourceMetaId) {
        qc.invalidateQueries({
          queryKey: ["source-meta", data.sourceMetaId, "access"],
        });
      }
    },
  });
}

export function useBulkRevokeAccess(userId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: Array<{ kind: string; name: string }>) =>
      apiFetch(`/api/users/${userId}/access:bulk`, {
        method: "POST",
        body: JSON.stringify({ action: "revoke", items }),
      }).then((r) => {
        if (!r.ok) return r.json().then((b: {detail?: string}) => Promise.reject(new Error(b?.detail ?? `HTTP ${r.status}`)));
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", userId, "access"] });
    },
  });
}
