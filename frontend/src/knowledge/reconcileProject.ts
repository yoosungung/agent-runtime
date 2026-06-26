export function pickFallbackProjectId(
  projectId: string | undefined,
  projects: { id: string }[] | undefined,
): string | null {
  if (!projects?.length) return null;
  if (projectId && projects.some((p) => p.id === projectId)) return projectId;
  return projects[0]?.id ?? null;
}
