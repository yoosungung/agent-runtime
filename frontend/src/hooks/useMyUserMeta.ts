import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch } from "../lib/api";
import type { UserMetaFormTemplate } from "../lib/userMetaTemplate";

export interface AccessResource {
  kind: "agent" | "mcp";
  name: string;
  version: string;
  source_meta_id: number;
  runtime_pool: string;
  has_user_meta: boolean;
  user_meta_required: boolean;
  template_description: string | null;
  template_field_count: number;
}

export interface MeUserMeta {
  kind: "agent" | "mcp";
  name: string;
  version: string;
  source_meta_id: number;
  source_config: Record<string, unknown>;
  user_meta_template: UserMetaFormTemplate;
  config: Record<string, unknown>;
  secrets_ref: string | null;
  updated_at: string | null;
}

export function useMyAccessResources(kind: "agent" | "mcp") {
  return useQuery({
    queryKey: ["me", "access-resources", kind],
    queryFn: () =>
      apiJson<{ items: AccessResource[]; total: number }>(
        `/api/me/access-resources?kind=${kind}`,
      ),
  });
}

export function useMyUserMeta(kind: "agent" | "mcp" | undefined, name: string | undefined) {
  return useQuery({
    queryKey: ["me", "user-meta", kind, name],
    queryFn: () =>
      apiJson<MeUserMeta>(
        `/api/me/user-meta?kind=${kind}&name=${encodeURIComponent(name!)}`,
      ),
    enabled: kind !== undefined && name !== undefined && name.length > 0,
  });
}

export function useUpsertMyUserMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      kind: "agent" | "mcp";
      name: string;
      config: Record<string, unknown>;
      secrets_ref?: string | null;
    }) =>
      apiJson<MeUserMeta>("/api/me/user-meta", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({
        queryKey: ["me", "user-meta", data.kind, data.name],
      });
      qc.invalidateQueries({
        queryKey: ["me", "access-resources", data.kind],
      });
    },
  });
}

export function useDeleteMyUserMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, name }: { kind: "agent" | "mcp"; name: string }) =>
      apiFetch(
        `/api/me/user-meta?kind=${kind}&name=${encodeURIComponent(name)}`,
        { method: "DELETE" },
      ).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return { kind, name };
      }),
    onSuccess: ({ kind, name }) => {
      qc.invalidateQueries({ queryKey: ["me", "user-meta", kind, name] });
      qc.invalidateQueries({ queryKey: ["me", "access-resources", kind] });
    },
  });
}
