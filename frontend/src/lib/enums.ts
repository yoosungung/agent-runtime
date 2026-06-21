/** Bundle upload pools — two-part `{kind}:{runtime_kind}` only. */
export const BUNDLE_AGENT_RUNTIME_KINDS = [
  "agent:compiled_graph",
  "agent:adk",
] as const;

export const BUNDLE_MCP_RUNTIME_KINDS = [
  "mcp:fastmcp",
  "mcp:mcp_sdk",
] as const;

/** Includes image-mode marker `*:custom` — not for bundle dropdowns. */
export const AGENT_RUNTIME_KINDS = [
  ...BUNDLE_AGENT_RUNTIME_KINDS,
  "agent:custom",
] as const;

export const MCP_RUNTIME_KINDS = [
  ...BUNDLE_MCP_RUNTIME_KINDS,
  "mcp:custom",
] as const;

export type AgentRuntimeKind = (typeof AGENT_RUNTIME_KINDS)[number];
export type McpRuntimeKind = (typeof MCP_RUNTIME_KINDS)[number];

export function getRuntimeKinds(kind: "agent" | "mcp"): readonly string[] {
  return kind === "agent" ? BUNDLE_AGENT_RUNTIME_KINDS : BUNDLE_MCP_RUNTIME_KINDS;
}
