import { describe, expect, it } from "vitest";
import {
  formatHermesModelValue,
  isHermesCompatibleContext,
  parseHermesModelValue,
} from "../lib/hermesModel";

describe("hermesModel", () => {
  it("parses platform default from empty model", () => {
    expect(parseHermesModelValue("")).toEqual({
      source: "platform",
      presetName: "",
      provider: "anthropic",
      modelId: "",
    });
    expect(formatHermesModelValue(parseHermesModelValue(""))).toBe("");
  });

  it("round-trips preset model", () => {
    const state = parseHermesModelValue("preset:CLAUDE_SONNET");
    expect(state.source).toBe("preset");
    expect(state.presetName).toBe("CLAUDE_SONNET");
    expect(formatHermesModelValue(state)).toBe("preset:CLAUDE_SONNET");
  });

  it("round-trips explicit colon model", () => {
    const state = parseHermesModelValue("anthropic:claude-sonnet-4-6");
    expect(state).toMatchObject({
      source: "explicit",
      provider: "anthropic",
      modelId: "claude-sonnet-4-6",
    });
    expect(formatHermesModelValue(state)).toBe("anthropic:claude-sonnet-4-6");
  });

  it("parses slash model into explicit form", () => {
    const state = parseHermesModelValue("openai/gpt-4o");
    expect(state).toMatchObject({
      source: "explicit",
      provider: "openai",
      modelId: "gpt-4o",
    });
    expect(formatHermesModelValue(state)).toBe("openai:gpt-4o");
  });

  it("flags Hermes-compatible context", () => {
    expect(isHermesCompatibleContext(16384)).toBe(false);
    expect(isHermesCompatibleContext(65536)).toBe(true);
    expect(isHermesCompatibleContext(131072)).toBe(true);
  });
});
