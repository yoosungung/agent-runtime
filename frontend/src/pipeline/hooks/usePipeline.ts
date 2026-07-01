import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson, formatApiErrorDetail, type PageResponse } from "../../lib/api";

export type SourceDriver = "sharepoint" | "gdrive" | "onedrive" | "manual";

export interface PipelineProject {
  tenant: string;
  id: string;
  slug: string;
  name: string;
  created_at: string | null;
}

export interface PipelineSource {
  tenant: string;
  id: string;
  project_id: string;
  name: string;
  driver: SourceDriver;
  source_id: string;
  config: Record<string, unknown>;
  credential_id: string | null;
  enabled: boolean;
  schedule_cron: string | null;
  last_batch_id: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PipelineRun {
  id: string;
  workflow_name: string;
  argo_uid: string | null;
  batch_id: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  project_id?: string | null;
  run_kind?: string;
}

export interface SourceWorkflowStatus {
  active: boolean;
  workflow_name: string | null;
  phase: string | null;
  batch_id: string | null;
  last_run_status: string | null;
  argo_available: boolean;
}

export interface PipelineDocumentSummary {
  document_id: string;
  source_id: string;
  content_hash: string;
  ingest_state: string;
  s3_raw_uri: string;
}

export interface PipelineSourceDocument extends PipelineDocumentSummary {
  filename: string;
}

export interface UploadFileResult {
  filename: string;
  status: string;
  skipped?: boolean | null;
  reason?: string | null;
  content_hash?: string | null;
  document_id?: string | null;
  s3_raw_uri?: string | null;
}

export interface CreateSourceInput {
  project_id: string;
  name: string;
  driver: SourceDriver;
  source_id: string;
  config: Record<string, unknown>;
  credential_id?: string | null;
  enabled?: boolean;
  schedule_cron?: string | null;
}

export interface UpdateSourceInput {
  source_id?: string;
  config?: Record<string, unknown>;
  enabled?: boolean;
  schedule_cron?: string | null;
}

export interface CreateProjectInput {
  name: string;
  slug?: string | null;
}

export function usePipelineProjects() {
  return useQuery({
    queryKey: ["pipeline", "projects"],
    queryFn: () =>
      apiJson<{ items: PipelineProject[] }>("/api/pipeline/projects"),
  });
}

export function usePipelineProject(id: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "projects", id],
    queryFn: () => apiJson<PipelineProject>(`/api/pipeline/projects/${id}`),
    enabled: Boolean(id),
  });
}

export interface KnowledgeBinding {
  tenant: string;
  project_id: string;
  project_slug: string;
  rag: { qdrant_collection: string; filter: Record<string, string> };
  graph: { nebula_space: string };
  wiki: { s3_prefix: string; vfs_mount: string };
}

export function usePipelineProjectBinding(id: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "projects", id, "binding"],
    queryFn: () =>
      apiJson<KnowledgeBinding>(`/api/pipeline/projects/${id}/binding`),
    enabled: Boolean(id),
  });
}

export function useCreatePipelineProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateProjectInput) =>
      apiJson<PipelineProject>("/api/pipeline/projects", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "projects"] });
    },
  });
}

export function usePipelineSources(
  projectId?: string,
  params?: { limit?: number; offset?: number },
) {
  const search = new URLSearchParams();
  if (projectId) search.set("project_id", projectId);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString() ? `?${search}` : "";
  return useQuery({
    queryKey: ["pipeline", "sources", projectId ?? "all", params ?? {}],
    queryFn: () =>
      apiJson<PageResponse<PipelineSource>>(`/api/pipeline/sources${qs}`),
  });
}

export function usePipelineSource(id: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "sources", id],
    queryFn: () => apiJson<PipelineSource>(`/api/pipeline/sources/${id}`),
    enabled: Boolean(id),
  });
}

export function useSourceWorkflowStatus(sourceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["pipeline", "sources", sourceId, "workflow-status"],
    queryFn: () =>
      apiJson<SourceWorkflowStatus>(
        `/api/pipeline/sources/${sourceId}/workflow-status`,
      ),
    enabled: Boolean(sourceId) && enabled,
    staleTime: 0,
  });
}

export function useCreatePipelineSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateSourceInput) =>
      apiJson<PipelineSource>("/api/pipeline/sources", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (_data, body) => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources"] });
      qc.invalidateQueries({
        queryKey: ["pipeline", "sources", body.project_id],
      });
    },
  });
}

export function useUpdatePipelineSource(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdateSourceInput) =>
      apiJson<PipelineSource>(`/api/pipeline/sources/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources"] });
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id] });
    },
  });
}

export function useDeletePipelineSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiJson<void>(`/api/pipeline/sources/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources"] });
    },
  });
}

export function useTestPipelineSource(id: string) {
  return useMutation({
    mutationFn: () =>
      apiJson<{ file_count: number; sample_names: string[] }>(
        `/api/pipeline/sources/${id}/test`,
        { method: "POST" },
      ),
  });
}

export function useRunPipelineSource(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts?: { sync_mode?: "delta" | "full" }) =>
      apiJson<{
        batch_id: string;
        manifest_key: string;
        file_count: number | null;
        workflow_name: string;
        argo_uid: string;
      }>(`/api/pipeline/sources/${id}/run`, {
        method: "POST",
        body: JSON.stringify(opts ?? { sync_mode: "full" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id] });
      qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
    },
  });
}

export interface PipelineRunsResponse extends PageResponse<PipelineRun> {
  argo_available: boolean;
}

export function usePipelineRuns(
  projectId?: string,
  params?: { limit?: number; offset?: number },
) {
  const search = new URLSearchParams();
  if (projectId) search.set("project_id", projectId);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString() ? `?${search}` : "";
  return useQuery({
    queryKey: ["pipeline", "runs", projectId ?? "all", params ?? {}],
    queryFn: () =>
      apiJson<PipelineRunsResponse>(`/api/pipeline/runs${qs}`),
  });
}

export function useSubmitProjectGraphrag(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (batchId: string) =>
      apiJson<{
        batch_id: string;
        chunks_key: string;
        document_count: number;
        workflow_name: string;
        workflow_template: string;
        argo_uid: string;
      }>(`/api/pipeline/projects/${projectId}/graphrag`, {
        method: "POST",
        body: JSON.stringify({ batch_id: batchId }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "runs", projectId] });
      qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
    },
  });
}

export function usePipelineSourceDocuments(
  id: string | undefined,
  ingestState?: string,
  params?: { limit?: number; offset?: number },
) {
  const search = new URLSearchParams();
  if (ingestState) search.set("ingest_state", ingestState);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString() ? `?${search}` : "";
  return useQuery({
    queryKey: ["pipeline", "sources", id, "documents", ingestState ?? "all", params ?? {}],
    queryFn: () =>
      apiJson<PageResponse<PipelineSourceDocument>>(
        `/api/pipeline/sources/${id}/documents${qs}`,
      ),
    enabled: Boolean(id),
  });
}

export function useUploadPipelineFiles(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (files: File[]) => {
      const form = new FormData();
      for (const file of files) {
        form.append("files", file);
      }
      const resp = await apiFetch(`/api/pipeline/sources/${id}/upload`, {
        method: "POST",
        body: form,
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw Object.assign(
          new Error(formatApiErrorDetail(body?.detail, `HTTP ${resp.status}`)),
          { status: resp.status, body },
        );
      }
      return resp.json() as Promise<{
        items: UploadFileResult[];
        uploaded_count: number;
        skipped_count: number;
      }>;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id, "documents"] });
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id] });
    },
  });
}

export function useIngestPipelineSource(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (documentIds: string[] = []) =>
      apiJson<{
        batch_id: string;
        manifest_key: string;
        file_count: number | null;
        workflow_name: string;
        argo_uid: string;
      }>(`/api/pipeline/sources/${id}/ingest`, {
        method: "POST",
        body: JSON.stringify({ document_ids: documentIds }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id, "documents"] });
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id] });
      qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
    },
  });
}
