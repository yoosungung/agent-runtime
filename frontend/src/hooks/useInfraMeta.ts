import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../lib/api";

/** Flat container env keys managed by the curated Platform Infra UI. */
export const INFRA_UI_ENV_KEYS = {
  opikUrl: "OPIK_URL",
  opikWorkspace: "OPIK_WORKSPACE",
  defaultLlmModel: "DEFAULT_LLM_MODEL",
  openaiApiBase: "OPENAI_API_BASE",
  llmRuntime: "LLM_RUNTIME",
  otlpEndpoint: "OTLP_ENDPOINT",
} as const;

/** Password fields shown in the UI (any valid env key allowed via API). */
export const INFRA_UI_SECRET_KEYS = [
  "OPENAI_API_KEY",
  "ANTHROPIC_API_KEY",
  "GOOGLE_API_KEY",
  "OPIK_API_KEY",
] as const;

export interface InfraMeta {
  scope: string;
  scope_key: string;
  /** Flat container env var names → values (comprehensive API surface). */
  env: Record<string, string>;
  secret_keys: string[];
  updated_at: string | null;
  reconciled?: boolean;
}

export interface InfraMetaUpsert {
  /** Partial patch — merges into stored env; empty string removes a key. */
  env?: Record<string, string>;
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
