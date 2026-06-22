import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "../pages/ChatPage";

const mockUseMyAccessResources = vi.fn();
const mockUseChatThreads = vi.fn();
const mockUseCreateChatThread = vi.fn();
const mockUseDeleteChatThread = vi.fn();
const mockUseTouchChatThread = vi.fn();
const mockGetChatThread = vi.fn();
const mockGetChatThreadMessages = vi.fn();
const mockMigrateLegacyChatSessions = vi.fn();

vi.mock("../hooks/useMyUserMeta", () => ({
  useMyAccessResources: (...args: unknown[]) => mockUseMyAccessResources(...args),
}));

vi.mock("../lib/chatThreads", () => ({
  useChatThreads: () => mockUseChatThreads(),
  useCreateChatThread: () => mockUseCreateChatThread(),
  useDeleteChatThread: () => mockUseDeleteChatThread(),
  useTouchChatThread: () => mockUseTouchChatThread(),
  getChatThread: (...args: unknown[]) => mockGetChatThread(...args),
  getChatThreadMessages: (...args: unknown[]) => mockGetChatThreadMessages(...args),
  migrateLegacyChatSessions: (...args: unknown[]) => mockMigrateLegacyChatSessions(...args),
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

const mockThread = {
  id: "thread-abc",
  agent_name: "research-orchestrator",
  thread_type: "langgraph",
  title: "Hello world",
  last_message_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  session_id: "session-abc",
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  mockMigrateLegacyChatSessions.mockResolvedValue(undefined);
  mockUseMyAccessResources.mockReturnValue({
    isLoading: false,
    data: { items: [mockAgent, mockAgentOther], total: 2 },
  });
  mockUseChatThreads.mockReturnValue({
    isLoading: false,
    data: { items: [mockThread], total: 1 },
  });
  mockUseCreateChatThread.mockReturnValue({
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue({
      ...mockThread,
      id: "thread-new",
      session_id: "session-new",
      title: "New Chat",
    }),
  });
  mockUseDeleteChatThread.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  });
  mockUseTouchChatThread.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(mockThread),
  });
  mockGetChatThread.mockResolvedValue(mockThread);
  mockGetChatThreadMessages.mockResolvedValue({
    messages: [{ role: "user", content: "Hello world" }],
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
    mockUseChatThreads.mockReturnValue({
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
    mockUseChatThreads.mockReturnValue({
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
    const mutateAsync = vi.fn().mockResolvedValue({
      ...mockThread,
      id: "thread-new",
      session_id: "session-new",
      title: "New Chat",
    });
    mockUseCreateChatThread.mockReturnValue({ isPending: false, mutateAsync });

    renderChatPage();

    selectSidebarAgent("research-orchestrator");
    startNewChat();

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith("research-orchestrator");
    });
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
    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({
        ...mockThread,
        id: "thread-1",
        session_id: "session-1",
      })
      .mockResolvedValueOnce({
        ...mockThread,
        id: "thread-2",
        session_id: "session-2",
        agent_name: "other-agent",
      });
    mockUseCreateChatThread.mockReturnValue({ isPending: false, mutateAsync });

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

  it("selects agent when restoring a recent chat by thread id", async () => {
    renderChatPage();

    fireEvent.click(screen.getByRole("button", { name: "Hello world" }));

    await waitFor(() => {
      expect(mockGetChatThread).toHaveBeenCalledWith("thread-abc");
      expect(mockGetChatThreadMessages).toHaveBeenCalledWith("thread-abc");
    });
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
