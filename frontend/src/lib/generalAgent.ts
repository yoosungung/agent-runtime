import type { GeneralVisibility } from "./generalVisibility";

interface GeneralConfig {
  system_prompt?: string;
  mcp_servers?: string[];
  knowledge_project_ids?: string[];
}

export function readGeneralConfig(
  config: Record<string, unknown>,
): GeneralConfig {
  const general = config.general;
  if (!general || typeof general !== "object" || Array.isArray(general)) {
    return {};
  }
  const g = general as Record<string, unknown>;
  return {
    system_prompt:
      typeof g.system_prompt === "string" ? g.system_prompt : undefined,
    mcp_servers: Array.isArray(g.mcp_servers)
      ? g.mcp_servers.filter((s): s is string => typeof s === "string")
      : undefined,
    knowledge_project_ids: Array.isArray(g.knowledge_project_ids)
      ? g.knowledge_project_ids.filter((s): s is string => typeof s === "string")
      : undefined,
  };
}

export function canManageGeneralAgent(
  item: {
    created_by_user_id?: number | null;
  },
  session: { user_id: number; role?: string } | null | undefined,
): boolean {
  if (!session) return false;
  if (session.role === "admin") return true;
  return item.created_by_user_id === session.user_id;
}

export type { GeneralVisibility };
