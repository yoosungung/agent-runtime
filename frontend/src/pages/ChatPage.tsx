import { useEffect, useRef, useState } from "react";
import { useMyAccessResources } from "../hooks/useMyUserMeta";
import { invokeAgentStream } from "../lib/agentsInvoke";
import { generateSessionId } from "../lib/sessionId";

interface Message {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export function ChatPage() {
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [sessionId, setSessionId] = useState<string>(generateSessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { data: agentList, isLoading: agentsLoading } = useMyAccessResources("agent");

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages]);

  function handleNewChat() {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setSessionId(generateSessionId());
    setMessages([]);
    setError(null);
    setIsStreaming(false);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || !selectedAgent || isStreaming) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setIsStreaming(true);

    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", streaming: true },
    ]);

    const ac = new AbortController();
    abortRef.current = ac;

    let accumulated = "";

    const flushAccumulated = () => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = {
            ...last,
            content: accumulated,
            streaming: true,
          };
        }
        return next;
      });
    };

    try {
      await invokeAgentStream(
        {
          agent: selectedAgent,
          input: { message: text },
          sessionId,
          stream: true,
        },
        {
          onText: (delta) => {
            accumulated += delta;
            flushAccumulated();
          },
          onError: (message) => {
            throw new Error(message);
          },
          onDone: () => {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "assistant") {
                next[next.length - 1] = { ...last, streaming: false };
              }
              return next;
            });
          },
        },
        ac.signal,
      );
    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Request failed");
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.streaming) {
          next.pop();
        }
        return next;
      });
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const agents = agentList?.items ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header
        data-testid="chat-header"
        className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pb-4"
      >
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900">Chat</h1>
        <div className="flex flex-col sm:flex-row gap-2 sm:items-center w-full sm:w-auto">
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="w-full sm:min-w-[12rem] border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={agentsLoading || isStreaming}
          >
          <option value="">
            {agentsLoading ? "Loading agents..." : "Select agent..."}
          </option>
          {agents.map((a) => (
            <option key={a.source_meta_id} value={a.name}>
              {a.name} ({a.version})
            </option>
          ))}
          </select>
          <button
            onClick={handleNewChat}
            className="text-sm px-3 py-2 border border-gray-300 rounded hover:bg-gray-50 w-full sm:w-auto"
          >
            New Chat
          </button>
        </div>
      </header>

      <div
        ref={messagesContainerRef}
        data-testid="chat-messages"
        className="flex-1 min-h-0 overflow-y-auto bg-white shadow rounded-lg p-4 space-y-4"
      >
        {messages.length === 0 && (
          <p className="text-sm text-gray-400 text-center mt-8">
            {selectedAgent
              ? "Send a message to start the conversation."
              : "Select an agent and send a message."}
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-full sm:max-w-[80%] rounded-lg px-4 py-2 text-sm whitespace-pre-wrap break-words ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-900"
              }`}
            >
              {msg.content}
              {msg.streaming && (
                <span className="inline-block w-1.5 h-4 ml-0.5 bg-current animate-pulse align-middle" />
              )}
            </div>
          </div>
        ))}
        {error && (
          <p className="text-sm text-red-600 text-center bg-red-50 border border-red-200 rounded px-3 py-2">
            {error}
          </p>
        )}
        <div ref={messagesEndRef} />
      </div>

      <footer
        data-testid="chat-composer"
        className="shrink-0 pt-4 bg-gray-50"
      >
        <div className="bg-white shadow rounded-lg p-3 flex flex-col sm:flex-row gap-3 sm:items-end">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={selectedAgent ? "Type a message... (Enter to send, Shift+Enter for newline)" : "Select an agent first"}
          disabled={!selectedAgent || isStreaming}
          rows={2}
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none disabled:bg-gray-50 disabled:text-gray-400"
        />
        <button
          onClick={handleSend}
          disabled={!selectedAgent || !input.trim() || isStreaming}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium h-fit w-full sm:w-auto"
        >
          {isStreaming ? "..." : "Send"}
        </button>
        </div>
      </footer>
    </div>
  );
}
