import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch } from "../lib/api";

export interface UserMeta {
  id: number;
  source_meta_id: number;
  principal_id: string;
  config: Record<string, unknown> | null;
  secrets_ref: string | null;
  updated_at: string;
}

export interface UserMetaUpsert {
  source_meta_id: number;
  principal_id: string;
  config: Record<string, unknown>;
  secrets_ref?: string | null;
}

export function useUserMeta(
  sourceMetaId: number | undefined,
  principalId: string | undefined,
) {
  return useQuery({
    queryKey: ["user-meta", sourceMetaId, principalId],
    queryFn: () =>
      apiJson<UserMeta>(
        `/api/user-meta?source_meta_id=${sourceMetaId}&principal=${encodeURIComponent(principalId!)}`,
      ),
    enabled: sourceMetaId !== undefined && principalId !== undefined,
    retry: (count, err: unknown) => (err as { status?: number })?.status !== 404 && count < 2,
  });
}

export function useUpsertUserMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UserMetaUpsert) =>
      apiJson<UserMeta>("/api/user-meta", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({
        queryKey: ["user-meta", data.source_meta_id, data.principal_id],
      });
      qc.invalidateQueries({
        queryKey: ["source-meta", data.source_meta_id],
      });
    },
  });
}

export function useDeleteUserMeta() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceMetaId,
      principalId,
    }: {
      sourceMetaId: number;
      principalId: string;
    }) =>
      apiFetch(
        `/api/user-meta?source_meta_id=${sourceMetaId}&principal=${encodeURIComponent(principalId)}`,
        { method: "DELETE" },
      ).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return { sourceMetaId, principalId };
      }),
    onSuccess: ({ sourceMetaId, principalId }) => {
      qc.invalidateQueries({
        queryKey: ["user-meta", sourceMetaId, principalId],
      });
      qc.invalidateQueries({ queryKey: ["source-meta", sourceMetaId] });
    },
  });
}
