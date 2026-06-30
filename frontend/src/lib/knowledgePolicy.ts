export function mcpSelectionRequiresKnowledge(
  mcpServers: string[],
  availableMcp: Array<{ name: string; requires_knowledge_project?: boolean }>,
): boolean {
  const byName = new Map(availableMcp.map((m) => [m.name, m]));
  return mcpServers.some((name) => byName.get(name)?.requires_knowledge_project);
}
