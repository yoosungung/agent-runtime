import { useQuery } from "@tanstack/react-query";
import { apiJson } from "../lib/api";

export interface ResourceStatusCounts {
  total: number;
  active: number;
  pending: number;
  failed: number;
  retired: number;
}

export interface ResourceSummary {
  agent: ResourceStatusCounts;
  mcp: ResourceStatusCounts;
}

export interface RecentIssue {
  id: number;
  kind: string;
  name: string;
  version: string;
  status: string;
  deploy_mode: string;
  created_at: string;
}

export interface PoolRuntimeStatus {
  runtime_kind: string;
  pod_count: number;
  active_requests: number;
  max_capacity: number;
}

export interface PoolSummary {
  available: boolean;
  error: string | null;
  agents: PoolRuntimeStatus[];
  mcp: PoolRuntimeStatus[];
}

export interface DashboardSummary {
  resources: ResourceSummary;
  recent_issues: RecentIssue[];
  pools: PoolSummary;
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: () => apiJson<DashboardSummary>("/api/dashboard/summary"),
    refetchInterval: 30_000,
  });
}
