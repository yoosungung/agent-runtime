import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const mockFetch = vi.fn();
global.fetch = mockFetch;

Object.defineProperty(document, "cookie", {
  get: vi.fn(() => "csrf_token=test-csrf-token"),
  configurable: true,
});

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("useDashboardSummary", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("fetches dashboard summary from /api/dashboard/summary", async () => {
    const summary = {
      resources: {
        agent: { total: 2, active: 1, pending: 1, failed: 0, retired: 0 },
        mcp: { total: 1, active: 1, pending: 0, failed: 0, retired: 0 },
      },
      recent_issues: [],
      pools: { available: false, error: "REDIS_URL not configured", agents: [], mcp: [] },
    };

    mockFetch.mockResolvedValueOnce({
      status: 200,
      ok: true,
      headers: { get: () => null },
      json: async () => summary,
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { useDashboardSummary } = await import("../hooks/useDashboardSummary");
    const { result } = renderHook(() => useDashboardSummary(), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(summary);
    expect(mockFetch.mock.calls[0][0]).toBe("/api/dashboard/summary");
  });
});
