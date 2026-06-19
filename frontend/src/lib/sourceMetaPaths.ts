import type { SourceMeta } from "../hooks/useSourceMeta";

export function sourceMetaListPath(item: Pick<SourceMeta, "kind" | "deploy_mode">): string {
  if (item.deploy_mode === "general") {
    return "/agents";
  }
  if (item.deploy_mode === "bundle") {
    return item.kind === "agent" ? "/bundle/agents" : "/bundle/mcp";
  }
  return item.kind === "agent" ? "/container/agents" : "/container/mcp";
}

export function sourceMetaDetailPath(item: Pick<SourceMeta, "kind" | "id">): string {
  return item.kind === "agent" ? `/agents/${item.id}` : `/mcp-servers/${item.id}`;
}
