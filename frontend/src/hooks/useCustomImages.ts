import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch } from "../lib/api";

export interface CustomImage {
  id: number;
  kind: "agent" | "mcp";
  name: string;
  version: string;
  slug: string;
  runtime_pool: string;
  image_uri: string | null;
  image_digest: string | null;
  config: Record<string, unknown>;
  status: "pending" | "active" | "failed" | "retired";
  deploy_mode: "image";
  created_at: string;
}

export interface CustomImageCreateBody {
  kind: "agent" | "mcp";
  name: string;
  version: string;
  image_uri: string;
  image_digest?: string;
  slug?: string;
  replicas_max?: number;
  resources?: Record<string, unknown>;
  image_pull_secret?: string;
  env?: Record<string, string>;
  config?: Record<string, unknown>;
}

export interface CustomImagePatchBody {
  replicas_max?: number;
  resources?: Record<string, unknown>;
  env?: Record<string, string>;
  config?: Record<string, unknown>;
}

export function useCustomImageList(kind?: "agent" | "mcp") {
  return useQuery({
    queryKey: ["custom-images", "list", kind],
    queryFn: () =>
      apiJson<CustomImage[]>(
        `/api/admin/custom-images${kind ? `?kind=${kind}` : ""}`,
      ),
  });
}

export function useCreateCustomImage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CustomImageCreateBody) =>
      apiJson<CustomImage>("/api/admin/custom-images", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-images", "list"] });
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}

export function usePatchCustomImage(kind: string, slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CustomImagePatchBody) =>
      apiJson<CustomImage>(`/api/admin/custom-images/${kind}/${slug}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-images", "list"] });
    },
  });
}

export function useDeleteCustomImage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, slug }: { kind: string; slug: string }) =>
      apiFetch(`/api/admin/custom-images/${kind}/${slug}`, {
        method: "DELETE",
      }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-images", "list"] });
      qc.invalidateQueries({ queryKey: ["source-meta", "list"] });
    },
  });
}
