import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock document.cookie for CSRF
Object.defineProperty(document, "cookie", {
  get: vi.fn(() => "csrf_token=test-csrf-token"),
  configurable: true,
});

describe("apiFetch", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("attaches CSRF header for POST requests", async () => {
    mockFetch.mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({}) });
    const { apiFetch } = await import("../lib/api");
    await apiFetch("/api/test", { method: "POST", body: JSON.stringify({}) });

    const [, init] = mockFetch.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("does NOT attach CSRF header for GET requests", async () => {
    mockFetch.mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({}) });
    const { apiFetch } = await import("../lib/api");
    await apiFetch("/api/test", { method: "GET" });

    const [, init] = mockFetch.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("adds credentials: include to every request", async () => {
    mockFetch.mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({}) });
    const { apiFetch } = await import("../lib/api");
    await apiFetch("/api/test");

    const [, init] = mockFetch.mock.calls[0];
    expect(init.credentials).toBe("include");
  });

  it("throws on non-ok with detail field", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 400,
      ok: false,
      json: async () => ({ detail: "bad request" }),
    });
    const { apiJson } = await import("../lib/api");
    await expect(apiJson("/api/test")).rejects.toThrow("bad request");
  });
});
