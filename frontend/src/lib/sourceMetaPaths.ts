import type { SourceMeta } from "../hooks/useSourceMeta";

export function sourceMetaListPath(item: Pick<SourceMeta, "kind" | "deploy_mode">): string {
  if (item.deploy_mode === "general") {
    return "/agents";
  }
  if (item.deploy_mode === "hermes_general") {
    return "/agents/hermes";
  }
  if (item.deploy_mode === "bundle") {
    return item.kind === "agent" ? "/bundle/agents" : "/bundle/mcp";
  }
  return item.kind === "agent" ? "/container/agents" : "/container/mcp";
}

export function sourceMetaDetailPath(
  item: Pick<SourceMeta, "kind" | "id" | "deploy_mode">,
): string {
  if (item.kind === "mcp") {
    return `/mcp-servers/${item.id}`;
  }
  if (item.deploy_mode === "general") {
    return `/agents/${item.id}`;
  }
  if (item.deploy_mode === "hermes_general") {
    return `/agents/hermes/${item.id}`;
  }
  return `/bundle/agents/${item.id}`;
}
