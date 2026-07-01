interface HermesConfig {
  soul?: string;
  mcp_servers?: string[];
  skills?: string[];
  model?: string;
}

export function readHermesConfig(
  config: Record<string, unknown>,
): HermesConfig {
  const hermes = config.hermes;
  if (!hermes || typeof hermes !== "object" || Array.isArray(hermes)) {
    return {};
  }
  const h = hermes as Record<string, unknown>;
  return {
    soul: typeof h.soul === "string" ? h.soul : undefined,
    mcp_servers: Array.isArray(h.mcp_servers)
      ? h.mcp_servers.filter((s): s is string => typeof s === "string")
      : undefined,
    skills: Array.isArray(h.skills)
      ? h.skills.filter((s): s is string => typeof s === "string")
      : undefined,
    model: typeof h.model === "string" ? h.model : undefined,
  };
}

export function parseSkillsInput(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
