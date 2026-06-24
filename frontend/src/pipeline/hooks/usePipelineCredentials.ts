import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../../lib/api";
import type { SourceDriver } from "./usePipeline";

export interface PipelineCredential {
  tenant: string;
  id: string;
  label: string;
  driver: SourceDriver;
  config: Record<string, unknown>;
  secret_keys: string[];
  oauth_status: "pending" | "connected" | "error";
  k8s_secret_name: string;
  created_at: string | null;
  updated_at: string | null;
}

export function usePipelineCredentials() {
  return useQuery({
    queryKey: ["pipeline", "credentials"],
    queryFn: () =>
      apiJson<{ items: PipelineCredential[] }>("/api/pipeline/credentials"),
  });
}

export function useCreatePipelineCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { label: string; driver: SourceDriver; config?: Record<string, unknown> }) =>
      apiJson<PipelineCredential>("/api/pipeline/credentials", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "credentials"] });
    },
  });
}

export function useDeletePipelineCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiJson<void>(`/api/pipeline/credentials/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline", "credentials"] });
    },
  });
}

export function useStartPipelineOAuth() {
  return useMutation({
    mutationFn: async (credentialId: string) => {
      const res = await apiJson<{ authorize_url: string }>(
        `/api/pipeline/credentials/${credentialId}/oauth/start`,
      );
      window.location.href = res.authorize_url;
    },
  });
}
