import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../lib/api";
import type { FrontierProvider, LlmMode, SlmRuntime } from "../lib/llmInfra";

export interface LlmPreset {
  id: number;
  name: string;
  description: string | null;
  mode: LlmMode;
  frontier_provider: FrontierProvider | null;
  model_id: string;
  openai_api_base: string | null;
  slm_runtime: SlmRuntime | null;
  is_default: boolean;
  api_key_configured: boolean;
  created_at: string;
  updated_at: string;
}

export interface LlmPresetCreate {
  name: string;
  description?: string | null;
  mode: LlmMode;
  frontier_provider?: FrontierProvider | null;
  model_id: string;
  openai_api_base?: string | null;
  slm_runtime?: SlmRuntime | null;
  is_default: boolean;
  api_key?: string | null;
}

export interface LlmPresetUpdate {
  description?: string | null;
  mode: LlmMode;
  frontier_provider?: FrontierProvider | null;
  model_id: string;
  openai_api_base?: string | null;
  slm_runtime?: SlmRuntime | null;
  is_default: boolean;
  api_key?: string | null;
}

export function useLlmPresets() {
  return useQuery({
    queryKey: ["llm-presets"],
    queryFn: () => apiJson<LlmPreset[]>("/api/llm-presets"),
  });
}

export function useCreateLlmPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: LlmPresetCreate) =>
      apiJson<LlmPreset>("/api/llm-presets", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-presets"] });
      // Invalidate infra meta too since reconciling modifies it
      qc.invalidateQueries({ queryKey: ["infra-meta"] });
    },
  });
}

export function useUpdateLlmPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: LlmPresetUpdate }) =>
      apiJson<LlmPreset>(`/api/llm-presets/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-presets"] });
      qc.invalidateQueries({ queryKey: ["infra-meta"] });
    },
  });
}

export function useDeleteLlmPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiJson<{ status: string }>(`/api/llm-presets/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm-presets"] });
      qc.invalidateQueries({ queryKey: ["infra-meta"] });
    },
  });
}
