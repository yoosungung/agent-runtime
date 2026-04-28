import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch, type PageResponse } from "../lib/api";

export interface SourceMeta {
  id: number;
  kind: "agent" | "mcp";
  name: string;
  version: string;
  runtime_pool: string;
  entrypoint: string;
  bundle_uri: string | null;
  checksum: string | null;
  sig_uri: string | null;
  config: Record<string, unknown>;
  retired: boolean;
  created_at: string;
  updated_at: string;
}

export interface AccessEntry {
  user_id: number;
  username: string;
  kind: string;
  name: string;
}

export interface SourceMetaListParams {
  kind?: "agent" | "mcp";
  name?: string;
  retired?: boolean;
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

export function useSourceMetaList(params: SourceMetaListParams) {
  return useQuery({
    queryKey: ["source-meta", "list", params],
    queryFn: () =>
      apiJson<PageResponse<SourceMeta>>(
        `/api/source-meta${buildQuery(params as Record<string, unknown>)}`,
      ),
  });
}

export function useSourceMetaById(id: number | undefined) {
  return useQuery({
    queryKey: ["source-meta", id],
    queryFn: () => apiJson<SourceMeta>(`/api/source-meta/${id}`),
    enabled: id !== undefined,
  });
}

export function useSourceMetaAccess(id: number | undefined, params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: ["source-meta", id, "access", params],
    queryFn: () =>
      apiJson<PageResponse<AccessEntry>>(
        `/api/source-meta/${id}/access${buildQuery((params ?? {}) as Record<string, unknown>)}`,
      ),
    enabled: id !== undefined,
  });
}

export function useCreateSourceMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiJson<SourceMeta>("/api/source-meta", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function useUploadBundle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) =>
      apiJson<SourceMeta>("/api/source-meta/bundle", {
        method: "POST",
        body: formData,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function usePatchSourceMeta(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<SourceMeta>) =>
      apiJson<SourceMeta>(`/api/source-meta/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", id] });
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function useRetireSourceMeta(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<SourceMeta>(`/api/source-meta/${id}/retire`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", id] });
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function useDeleteSourceMeta(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch(`/api/source-meta/${id}`, { method: "DELETE" }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function useUploadSignature(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) =>
      apiJson<SourceMeta>(`/api/source-meta/${id}/signature`, {
        method: "POST",
        body: formData,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-meta", id] });
    },
  });
}

export interface VerifyResult {
  ok: boolean;
  message: string;
}

export function useVerifySourceMeta(id: number) {
  return useMutation({
    mutationFn: () =>
      apiJson<VerifyResult>(`/api/source-meta/${id}/verify`, { method: "POST" }),
  });
}
