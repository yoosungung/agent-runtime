import { apiJson } from "./api";
import { getAgentsInvokeUrl } from "./env";
import { parseChatSseBlock } from "./chatStream";

export interface AgentInvokeRequest {
  agent: string;
  version?: string;
  input: Record<string, unknown>;
  sessionId?: string;
  stream?: boolean;
}

export interface AgentInvokeHandlers {
  onText: (delta: string) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

async function fetchAccessToken(): Promise<string> {
  const data = await apiJson<{ access_token: string }>("/api/auth/access-token");
  if (!data?.access_token) {
    throw new Error("Missing access token");
  }
  return data.access_token;
}

export async function invokeAgentStream(
  req: AgentInvokeRequest,
  handlers: AgentInvokeHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = await fetchAccessToken();
  const url = getAgentsInvokeUrl();

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "x-runtime-name": req.agent,
  };
  if (req.version) {
    headers["x-runtime-version"] = req.version;
  }
  if (req.sessionId) {
    headers["x-runtime-session-id"] = req.sessionId;
  }

  const body: Record<string, unknown> = {
    agent: req.agent,
    input: req.input,
    stream: req.stream ?? true,
  };
  if (req.version !== undefined) {
    body.version = req.version;
  }
  if (req.sessionId !== undefined) {
    body.session_id = req.sessionId;
  }

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "include",
    signal,
  });

  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    const detail =
      typeof errBody?.detail === "string"
        ? errBody.detail
        : `HTTP ${resp.status}`;
    handlers.onError(detail);
    return;
  }

  const reader = resp.body?.getReader();
  if (!reader) {
    handlers.onError("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buf = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, sep);
        buf = buf.slice(sep + 2);

        const parsed = parseChatSseBlock(block);
        if (parsed.error) {
          handlers.onError(parsed.error);
          return;
        }
        if (parsed.done) {
          handlers.onDone();
          return;
        }
        if (parsed.text) {
          handlers.onText(parsed.text);
        }
      }
    }
    handlers.onDone();
  } catch (e: unknown) {
    if (e instanceof Error && e.name === "AbortError") {
      return;
    }
    handlers.onError(e instanceof Error ? e.message : "Stream failed");
  }
}
