import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../lib/api";

export function useGrantAccess(userId: number, resourceSourceMetaId?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { kind: string; name: string }) =>
      apiFetch(`/api/users/${userId}/access`, {
        method: "POST",
        body: JSON.stringify(data),
      }).then((r) => {
        if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
        return data;
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", userId, "access"] });
      if (resourceSourceMetaId !== undefined) {
        qc.invalidateQueries({
          queryKey: ["source-meta", resourceSourceMetaId, "access"],
        });
      }
    },
  });
}

export function useRevokeAccess(userId: number, resourceSourceMetaId?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { kind: string; name: string }) =>
      apiFetch(
        `/api/users/${userId}/access?kind=${data.kind}&name=${data.name}`,
        { method: "DELETE" },
      ).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return data;
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", userId, "access"] });
      if (resourceSourceMetaId !== undefined) {
        qc.invalidateQueries({
          queryKey: ["source-meta", resourceSourceMetaId, "access"],
        });
      }
    },
  });
}
