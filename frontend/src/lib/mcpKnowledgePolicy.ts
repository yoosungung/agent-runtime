export function readMcpKnowledgeRequiresProject(
  config: Record<string, unknown>,
): boolean {
  const knowledge = config.knowledge;
  if (!knowledge || typeof knowledge !== "object" || Array.isArray(knowledge)) {
    return false;
  }
  return Boolean((knowledge as Record<string, unknown>).requires_project);
}

export function withMcpKnowledgeRequiresProject(
  config: Record<string, unknown>,
  requiresProject: boolean,
): Record<string, unknown> {
  return {
    ...config,
    knowledge: { requires_project: requiresProject },
  };
}
