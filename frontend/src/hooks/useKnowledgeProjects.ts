import { useQuery } from "@tanstack/react-query";
import { apiJson } from "../lib/api";
import type { KnowledgeBinding, PipelineProject } from "../pipeline/hooks/usePipeline";

export function useKnowledgeProjects() {
  return useQuery({
    queryKey: ["me", "knowledge-projects"],
    queryFn: () =>
      apiJson<{ items: PipelineProject[] }>("/api/me/knowledge-projects"),
  });
}

export function useKnowledgeProjectBinding(id: string | undefined) {
  return useQuery({
    queryKey: ["me", "knowledge-projects", id, "binding"],
    queryFn: () =>
      apiJson<KnowledgeBinding>(`/api/me/knowledge-projects/${id}/binding`),
    enabled: Boolean(id),
  });
}
