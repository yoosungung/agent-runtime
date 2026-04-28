export const AGENT_RUNTIME_KINDS = [
  "agent:compiled_graph",
  "agent:adk",
  "agent:custom",
] as const;

export const MCP_RUNTIME_KINDS = [
  "mcp:fastmcp",
  "mcp:mcp_sdk",
  "mcp:didim_rag",
  "mcp:t2sql",
] as const;

export type AgentRuntimeKind = (typeof AGENT_RUNTIME_KINDS)[number];
export type McpRuntimeKind = (typeof MCP_RUNTIME_KINDS)[number];

export function getRuntimeKinds(kind: "agent" | "mcp"): readonly string[] {
  return kind === "agent" ? AGENT_RUNTIME_KINDS : MCP_RUNTIME_KINDS;
}
