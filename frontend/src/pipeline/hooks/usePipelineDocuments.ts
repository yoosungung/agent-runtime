import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../../lib/api";
import type {
  PipelineDocumentSummary,
  PipelineSourceDocument,
} from "./usePipeline";

export interface DocumentDetail extends PipelineSourceDocument {
  project_id: string | null;
  dead_letter_error: Record<string, unknown> | null;
}

export interface Tombstone {
  content_hash?: string;
  document_id?: string;
  reason?: string;
  created_at?: string;
  [key: string]: unknown;
}

function projectDocsKey(projectId: string) {
  return ["pipeline", "projects", projectId, "documents"] as const;
}

export function useProjectDocuments(
  projectId: string | undefined,
  filters?: { ingest_state?: string; source_id?: string },
) {
  const params = new URLSearchParams();
  if (filters?.ingest_state) params.set("ingest_state", filters.ingest_state);
  if (filters?.source_id) params.set("source_id", filters.source_id);
  const qs = params.toString() ? `?${params}` : "";
  return useQuery({
    queryKey: [...projectDocsKey(projectId ?? ""), filters ?? {}],
    queryFn: () =>
      apiJson<{ items: PipelineSourceDocument[] }>(
        `/api/pipeline/projects/${projectId}/documents${qs}`,
      ),
    enabled: Boolean(projectId),
  });
}

export function useDocument(documentId: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "documents", documentId],
    queryFn: () => apiJson<DocumentDetail>(`/api/pipeline/documents/${documentId}`),
    enabled: Boolean(documentId),
  });
}

export function useProjectTombstones(projectId: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", "projects", projectId, "tombstones"],
    queryFn: () =>
      apiJson<{ items: Tombstone[] }>(
        `/api/pipeline/projects/${projectId}/tombstones`,
      ),
    enabled: Boolean(projectId),
  });
}

export function useProjectDeadLetters(projectId: string | undefined) {
  const qs = projectId
    ? `?project_id=${encodeURIComponent(projectId)}`
    : "";
  return useQuery({
    queryKey: ["pipeline", "dead-letters", projectId ?? "all"],
    queryFn: () =>
      apiJson<{ items: PipelineDocumentSummary[] }>(
        `/api/pipeline/dead-letters${qs}`,
      ),
    enabled: Boolean(projectId),
  });
}

export function usePurgeDocument(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { reason?: string; hard_raw?: boolean }) =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/documents/${documentId}/purge`,
        { method: "POST", body: JSON.stringify(body) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "documents", documentId] });
      qc.invalidateQueries({ queryKey: ["pipeline", "projects"] });
    },
  });
}

export function useRestoreDocument(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/documents/${documentId}/restore`,
        { method: "POST", body: "{}" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "documents", documentId] });
      qc.invalidateQueries({ queryKey: ["pipeline", "projects"] });
    },
  });
}

export function useReingestDocument(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/documents/${documentId}/reingest`,
        { method: "POST", body: "{}" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "documents", documentId] });
      qc.invalidateQueries({ queryKey: ["pipeline", "projects"] });
    },
  });
}

export function useReconcileProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/projects/${projectId}/reconcile`,
        { method: "POST", body: "{}" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "projects", projectId] });
    },
  });
}

export function useCleanupProject(projectId: string) {
  return useMutation({
    mutationFn: (dryRun: boolean) =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/projects/${projectId}/cleanup`,
        { method: "POST", body: JSON.stringify({ dry_run: dryRun }) },
      ),
  });
}

export function usePurgeProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason?: string) =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/projects/${projectId}/purge`,
        { method: "POST", body: JSON.stringify({ reason: reason ?? null }) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "projects"] });
    },
  });
}

export function usePurgeSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceId,
      reason,
    }: {
      sourceId: string;
      reason?: string;
    }) =>
      apiJson<Record<string, unknown>>(
        `/api/pipeline/sources/${sourceId}/purge`,
        { method: "POST", body: JSON.stringify({ reason: reason ?? null }) },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "sources"] });
    },
  });
}
