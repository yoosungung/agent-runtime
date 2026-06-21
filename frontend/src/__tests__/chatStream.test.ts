import { describe, expect, it } from "vitest";
import {
  extractTextFromAgentEvent,
  parseChatSseBlock,
} from "../lib/chatStream";

describe("extractTextFromAgentEvent", () => {
  it("extracts LangGraph on_chat_model_stream string content", () => {
    const text = extractTextFromAgentEvent({
      event: "on_chat_model_stream",
      data: { chunk: { content: "hello" } },
    });
    expect(text).toBe("hello");
  });

  it("extracts LangGraph content block list", () => {
    const text = extractTextFromAgentEvent({
      event: "on_chat_model_stream",
      data: {
        chunk: {
          content: [{ type: "text", text: "a" }, { type: "text", text: "b" }],
        },
      },
    });
    expect(text).toBe("ab");
  });

  it("extracts ADK content.parts text", () => {
    const text = extractTextFromAgentEvent({
      content: { parts: [{ text: "one" }, { text: "two" }] },
    });
    expect(text).toBe("one two");
  });

  it("extracts CUSTOM chunk and output", () => {
    expect(extractTextFromAgentEvent({ chunk: "delta" })).toBe("delta");
    expect(
      extractTextFromAgentEvent({
        output: { messages: [{ content: "final" }] },
      }),
    ).toBe("final");
  });

  it("passes through BFF-normalized text events", () => {
    expect(extractTextFromAgentEvent({ text: "bff" })).toBe("bff");
  });

  it("returns null for unknown events", () => {
    expect(extractTextFromAgentEvent({ event: "on_tool_start" })).toBeNull();
  });
});

describe("parseChatSseBlock", () => {
  it("accumulates text deltas and stops on [DONE]", () => {
    const events = [
      'data: {"text":"Hi"}\n\n',
      "data: [DONE]\n\n",
    ];
    let text = "";
    let done = false;
    for (const block of events) {
      const parsed = parseChatSseBlock(block);
      if (parsed.error) throw new Error(parsed.error);
      if (parsed.done) done = true;
      if (parsed.text) text += parsed.text;
    }
    expect(text).toBe("Hi");
    expect(done).toBe(true);
  });

  it("surfaces in-band errors", () => {
    const parsed = parseChatSseBlock('data: {"error":"boom"}\n\n');
    expect(parsed.error).toBe("boom");
  });
});
