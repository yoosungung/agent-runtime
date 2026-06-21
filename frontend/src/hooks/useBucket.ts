import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson } from "../lib/api";

export interface BucketInfo {
  backend: "local" | "s3";
  root_label: string;
  bucket?: string | null;
  prefix?: string | null;
  endpoint?: string | null;
}

export interface BucketObjectItem {
  key: string;
  name: string;
  kind: "file" | "folder";
  size: number | null;
  last_modified: string | null;
  ref_count: number;
  in_use: boolean;
}

export interface BucketListResponse {
  items: BucketObjectItem[];
  next_cursor?: string | null;
}

export function useBucketInfo() {
  return useQuery({
    queryKey: ["bucket", "info"],
    queryFn: () => apiJson<BucketInfo>("/api/bucket/info"),
  });
}

export function useBucketObjects(prefix: string, cursor?: string | null) {
  const params = new URLSearchParams();
  if (prefix) params.set("prefix", prefix);
  if (cursor) params.set("cursor", cursor);
  const qs = params.toString();
  return useQuery({
    queryKey: ["bucket", "objects", prefix, cursor ?? ""],
    queryFn: () => apiJson<BucketListResponse>(`/api/bucket/objects${qs ? `?${qs}` : ""}`),
  });
}

export function useCreateBucketFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { parent_prefix: string; name: string }) =>
      apiJson<BucketObjectItem>("/api/bucket/folders", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket"] });
    },
  });
}

export function useUploadBucketObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: { parent_prefix: string; file: File }) => {
      const form = new FormData();
      form.append("parent_prefix", data.parent_prefix);
      form.append("file", data.file);
      const resp = await apiFetch("/api/bucket/upload", { method: "POST", body: form });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw Object.assign(new Error(body?.detail ?? `HTTP ${resp.status}`), {
          status: resp.status,
          body,
        });
      }
      return resp.json() as Promise<{ key: string }>;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket"] });
    },
  });
}

export function useDeleteBucketObjects() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keys: string[]) =>
      apiFetch("/api/bucket/objects", {
        method: "DELETE",
        body: JSON.stringify({ keys }),
      }).then(async (resp) => {
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw Object.assign(new Error(body?.detail ?? `HTTP ${resp.status}`), {
            status: resp.status,
            body,
          });
        }
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket"] });
    },
  });
}

export function useMoveBucketObjects() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { sources: string[]; dest_prefix: string }) =>
      apiJson<{ keys: string[] }>("/api/bucket/move", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bucket"] });
    },
  });
}

export function useBucketDownloadUrl() {
  return useMutation({
    mutationFn: (key: string) =>
      apiJson<{ url: string }>(`/api/bucket/download-url?key=${encodeURIComponent(key)}`),
  });
}

export function formatBucketSize(size: number | null): string {
  if (size == null) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function bucketErrorMessage(err: unknown): string {
  if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 409) {
    return "Source Meta가 참조 중인 번들입니다. Source Meta에서 먼저 정리하세요.";
  }
  if (err instanceof Error) return err.message;
  return "Request failed";
}

export function prefixSegments(prefix: string): { label: string; prefix: string }[] {
  const trimmed = prefix.replace(/^\/+|\/+$/g, "");
  const segments: { label: string; prefix: string }[] = [{ label: "Root", prefix: "" }];
  if (!trimmed) return segments;
  let acc = "";
  for (const part of trimmed.split("/")) {
    acc = acc ? `${acc}${part}/` : `${part}/`;
    segments.push({ label: part, prefix: acc });
  }
  return segments;
}
