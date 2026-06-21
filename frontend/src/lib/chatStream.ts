export interface ParsedSseBlock {
  text?: string;
  error?: string;
  done?: boolean;
}

/** Pull user-facing text from agent-base or BFF-normalized SSE payloads. */
export function extractTextFromAgentEvent(event: Record<string, unknown>): string | null {
  if (typeof event.text === "string") {
    return event.text || null;
  }

  if (event.event === "on_chat_model_stream") {
    const chunk = (event.data as { chunk?: unknown } | undefined)?.chunk;
    if (typeof chunk === "object" && chunk !== null) {
      const content = (chunk as { content?: unknown }).content;
      if (typeof content === "string") {
        return content || null;
      }
      if (Array.isArray(content)) {
        const parts: string[] = [];
        for (const part of content) {
          if (typeof part === "object" && part !== null && (part as { type?: string }).type === "text") {
            parts.push(String((part as { text?: string }).text ?? ""));
          } else if (typeof part === "string") {
            parts.push(part);
          }
        }
        const joined = parts.join("");
        return joined || null;
      }
    }
    return null;
  }

  const content = event.content;
  if (typeof content === "object" && content !== null) {
    const parts = (content as { parts?: unknown[] }).parts ?? [];
    const texts = parts
      .filter((p): p is { text: string } => typeof p === "object" && p !== null && typeof (p as { text?: string }).text === "string")
      .map((p) => p.text);
    if (texts.length > 0) {
      return texts.join(" ");
    }
  }

  if ("chunk" in event && !("event" in event)) {
    const chunk = event.chunk;
    return typeof chunk === "string" ? chunk : JSON.stringify(chunk);
  }

  if ("output" in event) {
    const out = event.output;
    if (typeof out === "object" && out !== null) {
      const messages = (out as { messages?: unknown[] }).messages;
      if (Array.isArray(messages) && messages.length > 0) {
        const last = messages[messages.length - 1];
        if (typeof last === "object" && last !== null) {
          const messageContent = (last as { content?: unknown }).content;
          if (typeof messageContent === "string") {
            return messageContent;
          }
        }
      }
      for (const key of ["output", "response", "answer", "text", "result"]) {
        const val = (out as Record<string, unknown>)[key];
        if (typeof val === "string" && val) {
          return val;
        }
      }
    }
    return typeof out === "string" ? out : JSON.stringify(out);
  }

  return null;
}

export function parseChatSseBlock(block: string): ParsedSseBlock {
  for (const line of block.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trimStart();
    if (data === "[DONE]") {
      return { done: true };
    }
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(data) as Record<string, unknown>;
    } catch {
      continue;
    }
    if (typeof event.error === "string") {
      return { error: event.error };
    }
    const text = extractTextFromAgentEvent(event);
    if (text) {
      return { text };
    }
  }
  return {};
}
