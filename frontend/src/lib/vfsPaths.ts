/** Breadcrumb segments for VFS directory paths (root = `/`). */
export function vfsPathSegments(dirPath: string): { label: string; path: string }[] {
  const normalized = dirPath === "/" || dirPath === "" ? "/" : normalizeVfsDir(dirPath);
  const segments: { label: string; path: string }[] = [{ label: "Root", path: "/" }];
  if (normalized === "/") return segments;
  const parts = normalized.replace(/^\/|\/$/g, "").split("/");
  let acc = "/";
  for (const part of parts) {
    acc = `${acc}${part}/`;
    segments.push({ label: part, path: acc });
  }
  return segments;
}

export function normalizeVfsDir(path: string): string {
  if (!path || path === "/") return "/";
  const trimmed = path.startsWith("/") ? path : `/${path}`;
  return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
}

export function joinVfsPath(parent: string, name: string): string {
  const base = parent === "/" ? "" : parent.replace(/\/$/, "");
  return `${base}/${name}`.replace(/\/+/g, "/");
}

export function formatVfsSize(size: number | null | undefined): string {
  if (size == null) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function vfsAgentBrowserPath(kind: string, name: string): string {
  return `/vfs/agent/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`;
}
