import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const mockAgent = {
  kind: "agent" as const,
  name: "research-orchestrator",
  version: "v1",
  source_meta_id: 4,
  runtime_pool: "agent:compiled_graph",
  has_user_meta: false,
  user_meta_required: false,
  template_description: null,
  template_field_count: 0,
};

const mockAgentOther = {
  ...mockAgent,
  name: "other-agent",
  source_meta_id: 5,
  version: "v2",
};

function createLocalStorageMock() {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("localStorage", createLocalStorageMock());
  mockUseMyAccessResources.mockReturnValue({
    isLoading: false,
    data: { items: [mockAgent, mockAgentOther], total: 2 },
  });
});

function selectSidebarAgent(name: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`${name} \\(`) }));
}

function startNewChat() {
  fireEvent.click(screen.getByRole("button", { name: /New Chat/i }));
}

function renderChatPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

describe("ChatPage", () => {
  it("renders on insecure HTTP context without crypto.randomUUID", () => {
    vi.stubGlobal("crypto", {});

    mockUseMyAccessResources.mockReturnValue({
      isLoading: false,
      data: { items: [], total: 0 },
    });

    renderChatPage();
    expect(screen.getByRole("heading", { name: "Chat" })).toBeInTheDocument();

    vi.unstubAllGlobals();
  });

  it("keeps message list scrollable between fixed header and composer", () => {
    mockUseMyAccessResources.mockReturnValue({
      isLoading: false,
      data: { items: [], total: 0 },
    });

    renderChatPage();

    const messages = screen.getByTestId("chat-messages");
    expect(messages).toHaveClass("overflow-y-auto");
    expect(messages).toHaveClass("flex-1");
    expect(screen.getByTestId("chat-header")).toBeInTheDocument();
    expect(screen.getByTestId("chat-composer")).toBeInTheDocument();
  });

  it("shows agents from access-resources, not all source-meta", async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "research-orchestrator (v1)" })).toBeInTheDocument();
    });
    expect(mockUseMyAccessResources).toHaveBeenCalledWith("agent");
  });

  it("disables New Chat when no agent is selected", () => {
    renderChatPage();

    expect(screen.getByRole("button", { name: /New Chat/i })).toBeDisabled();
  });

  it("starts a new chat with the sidebar agent copied at that moment", async () => {
    renderChatPage();

    selectSidebarAgent("research-orchestrator");
    startNewChat();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chat: research-orchestrator" })).toBeInTheDocument();
    });
    expect(
      screen.getByText("Start your conversation with research-orchestrator"),
    ).toBeInTheDocument();
  });

  it("does not change the active chat when switching sidebar agent", async () => {
    renderChatPage();

    selectSidebarAgent("research-orchestrator");
    startNewChat();
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chat: research-orchestrator" })).toBeInTheDocument();
    });

    selectSidebarAgent("other-agent");

    expect(screen.getByRole("heading", { name: "Chat: research-orchestrator" })).toBeInTheDocument();
    expect(screen.getByText("Talking to research-orchestrator")).toBeInTheDocument();
  });

  it("uses the sidebar agent when starting another new chat", async () => {
    renderChatPage();

    selectSidebarAgent("research-orchestrator");
    startNewChat();
    selectSidebarAgent("other-agent");
    startNewChat();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chat: other-agent" })).toBeInTheDocument();
    });
    expect(screen.getByText("Talking to other-agent")).toBeInTheDocument();
  });

  it("selects agent when restoring a recent chat by session id", async () => {
    localStorage.setItem(
      "agents_chat_sessions",
      JSON.stringify([
        {
          id: "session-abc",
          agentName: "research-orchestrator",
          title: "Hello world",
          timestamp: Date.now(),
          messages: [{ role: "user", content: "Hello world" }],
        },
      ]),
    );

    renderChatPage();

    fireEvent.click(screen.getByRole("button", { name: "Hello world" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chat: research-orchestrator" })).toBeInTheDocument();
    });
    expect(screen.getByTestId("chat-messages")).toHaveTextContent("Hello world");
    expect(screen.getByText("Talking to research-orchestrator")).toBeInTheDocument();

    selectSidebarAgent("other-agent");
    expect(screen.getByRole("heading", { name: "Chat: research-orchestrator" })).toBeInTheDocument();
    expect(screen.getByText("Talking to research-orchestrator")).toBeInTheDocument();
  });
});
