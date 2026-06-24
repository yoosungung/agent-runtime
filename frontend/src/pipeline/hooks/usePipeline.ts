import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../../lib/api";

export type SourceDriver = "sharepoint" | "gdrive" | "onedrive";

export interface PipelineSource {
  tenant: string;
  id: string;
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
}

export interface PipelineDocumentSummary {
  document_id: string;
  source_id: string;
  content_hash: string;
  ingest_state: string;
  s3_raw_uri: string;
}

export interface CreateSourceInput {
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

export function usePipelineSources() {
  return useQuery({
    queryKey: ["pipeline", "sources"],
    queryFn: () =>
      apiJson<{ items: PipelineSource[] }>("/api/pipeline/sources"),
  });
}

export function usePipelineSource(id: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "sources", id],
    queryFn: () => apiJson<PipelineSource>(`/api/pipeline/sources/${id}`),
    enabled: Boolean(id),
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources"] });
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
    mutationFn: () =>
      apiJson<{
        batch_id: string;
        manifest_key: string;
        file_count: number | null;
        workflow_name: string;
        argo_uid: string;
      }>(`/api/pipeline/sources/${id}/run`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources", id] });
      qc.invalidateQueries({ queryKey: ["pipeline", "runs"] });
    },
  });
}

export function usePipelineRuns() {
  return useQuery({
    queryKey: ["pipeline", "runs"],
    queryFn: () =>
      apiJson<{
        runs: PipelineRun[];
        recent_documents: PipelineDocumentSummary[];
      }>("/api/pipeline/runs"),
  });
}

export function usePipelineDeadLetters() {
  return useQuery({
    queryKey: ["pipeline", "dead-letters"],
    queryFn: () =>
      apiJson<{ items: PipelineDocumentSummary[] }>(
        "/api/pipeline/dead-letters",
      ),
  });
}
