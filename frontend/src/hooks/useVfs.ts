import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson } from "../lib/api";

export interface VfsAgentSummary {
  kind: string;
  name: string;
  version: string;
  visibility: string;
  retired: boolean;
  vfs_enabled: boolean;
  file_count: number;
  total_bytes: number;
  last_modified: string | null;
}

export interface VfsEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  modified_at: string | null;
}

export interface VfsFile {
  path: string;
  content: string;
  encoding: string;
  modified_at: string | null;
}

export function useVfsAgents(filters?: {
  name?: string;
  include_retired?: boolean;
}) {
  const params = new URLSearchParams();
  if (filters?.name) params.set("name", filters.name);
  if (filters?.include_retired) params.set("include_retired", "true");
  const qs = params.toString();
  return useQuery({
    queryKey: ["vfs", "agents", filters?.name ?? "", filters?.include_retired ?? false],
    queryFn: () =>
      apiJson<{ items: VfsAgentSummary[] }>(`/api/vfs/agents${qs ? `?${qs}` : ""}`),
  });
}

export function useVfsEntries(kind: string, name: string, path: string) {
  const params = new URLSearchParams({ path });
  return useQuery({
    queryKey: ["vfs", "entries", kind, name, path],
    queryFn: () =>
      apiJson<{ items: VfsEntry[] }>(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/entries?${params}`,
      ),
  });
}

export function useVfsFile(kind: string, name: string, path: string | null) {
  return useQuery({
    queryKey: ["vfs", "file", kind, name, path ?? ""],
    enabled: !!path,
    queryFn: () =>
      apiJson<VfsFile>(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/files?path=${encodeURIComponent(path!)}`,
      ),
  });
}


export function useCreateVfsFile(kind: string, name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { path: string; content: string }) =>
      apiJson<VfsFile>(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/files`,
        { method: "PUT", body: JSON.stringify(data) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vfs", "entries", kind, name] });
      qc.invalidateQueries({ queryKey: ["vfs", "agents"] });
    },
  });
}

export function usePatchVfsFile(kind: string, name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { path: string; content: string }) =>
      apiJson<VfsFile>(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/files`,
        { method: "PATCH", body: JSON.stringify(data) },
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["vfs", "entries", kind, name] });
      qc.invalidateQueries({ queryKey: ["vfs", "file", kind, name, vars.path] });
    },
  });
}

export function useDeleteVfsPath(kind: string, name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      apiFetch(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/files?path=${encodeURIComponent(path)}`,
        { method: "DELETE" },
      ).then(async (resp) => {
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(
            typeof body?.detail === "string" ? body.detail : `HTTP ${resp.status}`,
          );
        }
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vfs", "entries", kind, name] });
      qc.invalidateQueries({ queryKey: ["vfs", "agents"] });
    },
  });
}

export function useCreateVfsFolder(kind: string, name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { parent_path: string; name: string }) =>
      apiJson<VfsEntry>(
        `/api/vfs/agents/${encodeURIComponent(kind)}/${encodeURIComponent(name)}/folders`,
        { method: "POST", body: JSON.stringify(data) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vfs", "entries", kind, name] });
    },
  });
}

export function vfsErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Request failed";
}
