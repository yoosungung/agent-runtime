import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../lib/api";

export interface InfraMeta {
  scope: string;
  scope_key: string;
  env: {
    opik_url?: string | null;
    opik_workspace?: string;
    default_llm_model?: string | null;
    otlp_endpoint?: string | null;
  };
  secret_keys: string[];
  updated_at: string | null;
  reconciled?: boolean;
}

export interface InfraMetaUpsert {
  env?: InfraMeta["env"];
  secrets?: Record<string, string>;
}

export function useInfraMeta() {
  return useQuery({
    queryKey: ["infra-meta"],
    queryFn: () => apiJson<InfraMeta>("/api/infra-meta"),
  });
}

export function useUpsertInfraMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: InfraMetaUpsert) =>
      apiJson<InfraMeta>("/api/infra-meta", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["infra-meta"] });
    },
  });
}
