import { useEffect, useRef, useState } from "react";
import { useSourceMetaList } from "../hooks/useSourceMeta";
import { apiFetch } from "../lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

function generateSessionId(): string {
  return crypto.randomUUID();
}

export function ChatPage() {
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [sessionId, setSessionId] = useState<string>(generateSessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { data: agentList, isLoading: agentsLoading } = useSourceMetaList({
    kind: "agent",
    retired: false,
    limit: 100,
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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

    try {
      const resp = await apiFetch("/api/chat/invoke", {
        method: "POST",
        body: JSON.stringify({
          agent: selectedAgent,
          input: { message: text },
          session_id: sessionId,
          stream: true,
        }),
        signal: ac.signal,
      });

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${resp.status}`);
      }

      const reader = resp.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let accumulated = "";
      let buf = "";

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

      streamLoop: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        let sep: number;
        while ((sep = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, sep);
          buf = buf.slice(sep + 2);

          for (const line of block.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const data = line.slice(5).trimStart();
            if (data === "[DONE]") break streamLoop;
            let event: { text?: string; error?: string };
            try {
              event = JSON.parse(data);
            } catch {
              continue;
            }
            if (typeof event.error === "string") {
              throw new Error(event.error);
            }
            if (typeof event.text === "string") {
              accumulated += event.text;
              flushAccumulated();
            }
          }
        }
      }

      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, streaming: false };
        }
        return next;
      });
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
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center gap-4 mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Chat</h1>
        <div className="flex-1" />
        <select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={agentsLoading || isStreaming}
        >
          <option value="">
            {agentsLoading ? "Loading agents..." : "Select agent..."}
          </option>
          {agents.map((a) => (
            <option key={a.id} value={a.name}>
              {a.name} ({a.version})
            </option>
          ))}
        </select>
        <button
          onClick={handleNewChat}
          className="text-sm px-3 py-2 border border-gray-300 rounded hover:bg-gray-50"
        >
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-white shadow rounded-lg p-4 space-y-4 mb-4">
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
              className={`max-w-[80%] rounded-lg px-4 py-2 text-sm whitespace-pre-wrap break-words ${
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

      {/* Input */}
      <div className="bg-white shadow rounded-lg p-3 flex gap-3 items-end">
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
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium h-fit"
        >
          {isStreaming ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}
