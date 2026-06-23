import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, type PageResponse } from "./api";

export interface ChatThreadListItem {
  id: string;
  agent_name: string;
  agent_version: string;
  thread_type: string;
  title: string;
  last_message_at: string;
  created_at: string;
}

export interface ChatThreadDetail extends ChatThreadListItem {
  session_id: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const THREADS_KEY = ["chat", "threads"] as const;

export async function listChatThreads(
  limit = 50,
  offset = 0,
): Promise<PageResponse<ChatThreadListItem>> {
  return apiJson(`/api/me/chat/threads?limit=${limit}&offset=${offset}`);
}

export async function createChatThread(
  agentName: string,
  sessionId?: string,
): Promise<ChatThreadDetail> {
  const body: Record<string, string> = { agent_name: agentName };
  if (sessionId) {
    body.session_id = sessionId;
  }
  return apiJson("/api/me/chat/threads", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getChatThread(threadId: string): Promise<ChatThreadDetail> {
  return apiJson(`/api/me/chat/threads/${threadId}`);
}

export async function deleteChatThread(threadId: string): Promise<void> {
  await apiJson(`/api/me/chat/threads/${threadId}`, { method: "DELETE" });
}

export async function touchChatThread(
  threadId: string,
  title?: string,
): Promise<ChatThreadListItem> {
  return apiJson(`/api/me/chat/threads/${threadId}/touch`, {
    method: "POST",
    body: JSON.stringify(title ? { title } : {}),
  });
}

export async function getChatThreadMessages(
  threadId: string,
): Promise<{ messages: ChatMessage[] }> {
  return apiJson(`/api/me/chat/threads/${threadId}/messages`);
}

export function useChatThreads() {
  return useQuery({
    queryKey: THREADS_KEY,
    queryFn: () => listChatThreads(),
  });
}

export function useCreateChatThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentName: string) => createChatThread(agentName),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}

export function useDeleteChatThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) => deleteChatThread(threadId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}

export function useTouchChatThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, title }: { threadId: string; title?: string }) =>
      touchChatThread(threadId, title),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}

export function useChatThreadMessages(threadId: string | null) {
  return useQuery({
    queryKey: [...THREADS_KEY, threadId, "messages"],
    queryFn: () => getChatThreadMessages(threadId!),
    enabled: Boolean(threadId),
  });
}

const LEGACY_STORAGE_KEY = "agents_chat_sessions";

interface LegacyChatSession {
  id: string;
  agentName: string;
  title: string;
  timestamp: number;
}

/** One-time import of legacy localStorage sessions into the thread registry. */
export async function migrateLegacyChatSessions(
  allowedAgents: Set<string>,
): Promise<void> {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LEGACY_STORAGE_KEY);
  } catch {
    return;
  }
  if (!raw) return;

  let sessions: LegacyChatSession[];
  try {
    sessions = JSON.parse(raw) as LegacyChatSession[];
  } catch {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    return;
  }

  for (const session of sessions) {
    if (!allowedAgents.has(session.agentName)) continue;
    try {
      const created = await createChatThread(session.agentName, session.id);
      if (session.title && session.title !== "New Chat") {
        await touchChatThread(created.id, session.title);
      }
    } catch {
      // best-effort migration
    }
  }

  localStorage.removeItem(LEGACY_STORAGE_KEY);
}
