import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "../pages/ChatPage";

const mockUseMyAccessResources = vi.fn();

vi.mock("../hooks/useMyUserMeta", () => ({
  useMyAccessResources: (...args: unknown[]) => mockUseMyAccessResources(...args),
}));

vi.mock("../lib/agentsInvoke", () => ({
  invokeAgentStream: vi.fn(),
}));

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

function renderChatPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

describe("ChatPage", () => {
  it("shows agents from access-resources, not all source-meta", async () => {
    mockUseMyAccessResources.mockReturnValue({
      isLoading: false,
      data: {
        items: [
          {
            kind: "agent",
            name: "research-orchestrator",
            version: "v1",
            source_meta_id: 4,
            runtime_pool: "agent:compiled_graph",
            has_user_meta: false,
            user_meta_required: false,
            template_description: null,
            template_field_count: 0,
          },
        ],
        total: 1,
      },
    });

    renderChatPage();

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "research-orchestrator (v1)" })).toBeInTheDocument();
    });
    expect(mockUseMyAccessResources).toHaveBeenCalledWith("agent");
  });
});
