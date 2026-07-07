import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson, type PageResponse } from "../lib/api";

export interface VfsAgentSummary {
  kind: string;
  name: string;
  version: string;
  deploy_mode: "general" | "hermes_general";
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
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (filters?.name) params.set("name", filters.name);
  if (filters?.include_retired) params.set("include_retired", "true");
  if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return useQuery({
    queryKey: [
      "vfs",
      "agents",
      filters?.name ?? "",
      filters?.include_retired ?? false,
      filters?.limit ?? 50,
      filters?.offset ?? 0,
    ],
    queryFn: () =>
      apiJson<PageResponse<VfsAgentSummary>>(`/api/vfs/agents${qs ? `?${qs}` : ""}`),
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

export interface VfsUserSummary {
  user_id: number;
  username: string;
  tenant: string;
  file_count: number;
  total_bytes: number;
  last_modified: string | null;
}

export interface VfsWikiProjectSummary {
  project_id: string;
  slug: string;
  name: string;
  vfs_mount: string;
  file_count: number;
  total_bytes: number;
  last_modified: string | null;
}

export function useVfsUsers(filters?: { limit?: number; offset?: number }) {
  const params = new URLSearchParams();
  if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return useQuery({
    queryKey: ["vfs", "users", filters?.limit ?? 50, filters?.offset ?? 0],
    queryFn: () =>
      apiJson<PageResponse<VfsUserSummary>>(`/api/vfs/users${qs ? `?${qs}` : ""}`),
  });
}

export function useVfsWikiProjects(filters?: { limit?: number; offset?: number }) {
  const params = new URLSearchParams();
  if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return useQuery({
    queryKey: ["vfs", "wiki", "projects", filters?.limit ?? 50, filters?.offset ?? 0],
    queryFn: () =>
      apiJson<PageResponse<VfsWikiProjectSummary>>(
        `/api/vfs/wiki/projects${qs ? `?${qs}` : ""}`,
      ),
  });
}

export function useVfsUserEntries(userId: string, path: string) {
  const params = new URLSearchParams({ path });
  return useQuery({
    queryKey: ["vfs", "user", "entries", userId, path],
    queryFn: () =>
      apiJson<{ items: VfsEntry[] }>(
        `/api/vfs/users/${encodeURIComponent(userId)}/entries?${params}`,
      ),
  });
}

export function useVfsUserFile(userId: string, path: string | null) {
  return useQuery({
    queryKey: ["vfs", "user", "file", userId, path ?? ""],
    enabled: !!path,
    queryFn: () =>
      apiJson<VfsFile>(
        `/api/vfs/users/${encodeURIComponent(userId)}/files?path=${encodeURIComponent(path!)}`,
      ),
  });
}

export function usePatchVfsUserFile(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { path: string; content: string }) =>
      apiJson<VfsFile>(`/api/vfs/users/${encodeURIComponent(userId)}/files`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["vfs", "user", "entries", userId] });
      qc.invalidateQueries({ queryKey: ["vfs", "user", "file", userId, vars.path] });
    },
  });
}

export function useVfsWikiEntries(projectId: string, path: string) {
  const params = new URLSearchParams({ path });
  return useQuery({
    queryKey: ["vfs", "wiki", "entries", projectId, path],
    queryFn: () =>
      apiJson<{ items: VfsEntry[] }>(
        `/api/vfs/wiki/projects/${encodeURIComponent(projectId)}/entries?${params}`,
      ),
  });
}

export function useVfsWikiFile(projectId: string, path: string | null) {
  return useQuery({
    queryKey: ["vfs", "wiki", "file", projectId, path ?? ""],
    enabled: !!path,
    queryFn: () =>
      apiJson<VfsFile>(
        `/api/vfs/wiki/projects/${encodeURIComponent(projectId)}/files?path=${encodeURIComponent(path!)}`,
      ),
  });
}

export function usePatchVfsWikiFile(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { path: string; content: string }) =>
      apiJson<VfsFile>(`/api/vfs/wiki/projects/${encodeURIComponent(projectId)}/files`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["vfs", "wiki", "entries", projectId] });
      qc.invalidateQueries({ queryKey: ["vfs", "wiki", "file", projectId, vars.path] });
    },
  });
}
