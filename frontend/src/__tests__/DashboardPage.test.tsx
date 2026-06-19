import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "../pages/DashboardPage";

vi.mock("../hooks/useSession", () => ({
  useSession: () => ({
    data: { username: "admin", tenant: "acme", role: "admin" as const, user_id: 1, must_change_password: false },
  }),
}));

vi.mock("../hooks/useDashboardSummary", () => ({
  useDashboardSummary: () => ({
    data: {
      resources: {
        agent: { total: 3, active: 2, pending: 1, failed: 0, retired: 0 },
        mcp: { total: 2, active: 1, pending: 0, failed: 1, retired: 0 },
      },
      recent_issues: [
        {
          id: 10,
          kind: "mcp",
          name: "broken-mcp",
          version: "v1",
          status: "failed",
          deploy_mode: "image",
          created_at: "2026-06-19T10:00:00Z",
        },
      ],
      pools: {
        available: true,
        error: null,
        agents: [
          {
            runtime_kind: "compiled_graph",
            pod_count: 2,
            active_requests: 4,
            max_capacity: 64,
          },
        ],
        mcp: [
          {
            runtime_kind: "fastmcp",
            pod_count: 1,
            active_requests: 0,
            max_capacity: 32,
          },
        ],
      },
    },
    isLoading: false,
    isError: false,
  }),
}));

function renderDashboard() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardPage", () => {
  it("shows agent and mcp resource status counts", () => {
    renderDashboard();

    expect(screen.getByText("Agent Resources")).toBeInTheDocument();
    expect(screen.getByText("MCP Resources")).toBeInTheDocument();
    expect(screen.getByText("3 registered")).toBeInTheDocument();
    expect(screen.getByText("2 registered")).toBeInTheDocument();
    expect(screen.getByText("Status Monitoring")).toBeInTheDocument();
  });

  it("shows runtime pool monitoring and recent issues", () => {
    renderDashboard();

    expect(screen.getByText("Runtime Pools")).toBeInTheDocument();
    expect(screen.getByText("compiled_graph")).toBeInTheDocument();
    expect(screen.getByText("fastmcp")).toBeInTheDocument();
    expect(screen.getByText("broken-mcp")).toBeInTheDocument();
  });
});
