import { describe, expect, it } from "vitest";
import {
  DEFAULT_LLM_INFRA,
  parseLlmInfraFromEnv,
  serializeLlmInfraToEnv,
} from "../lib/llmInfra";

describe("parseLlmInfraFromEnv", () => {
  it("parses frontier OpenAI model spec", () => {
    expect(
      parseLlmInfraFromEnv({ DEFAULT_LLM_MODEL: "openai:gpt-4o-mini" }),
    ).toEqual({
      mode: "frontier",
      frontierProvider: "openai",
      modelId: "gpt-4o-mini",
      openaiApiBase: "",
      slmRuntime: "vllm",
    });
  });

  it("parses frontier Anthropic model spec", () => {
    expect(
      parseLlmInfraFromEnv({ DEFAULT_LLM_MODEL: "anthropic:claude-sonnet-4-6" }),
    ).toEqual({
      mode: "frontier",
      frontierProvider: "anthropic",
      modelId: "claude-sonnet-4-6",
      openaiApiBase: "",
      slmRuntime: "vllm",
    });
  });

  it("parses self-hosted vLLM config from OPENAI_API_BASE", () => {
    expect(
      parseLlmInfraFromEnv({
        DEFAULT_LLM_MODEL: "openai:meta-llama/Llama-3.1-8B-Instruct",
        OPENAI_API_BASE: "http://vllm:8000/v1",
        LLM_RUNTIME: "vllm",
      }),
    ).toEqual({
      mode: "openai_compatible",
      frontierProvider: "openai",
      modelId: "meta-llama/Llama-3.1-8B-Instruct",
      openaiApiBase: "http://vllm:8000/v1",
      slmRuntime: "vllm",
    });
  });

  it("parses self-hosted SGLang config", () => {
    expect(
      parseLlmInfraFromEnv({
        DEFAULT_LLM_MODEL: "openai:Qwen/Qwen2.5-7B-Instruct",
        OPENAI_API_BASE: "http://sglang:30000/v1",
        LLM_RUNTIME: "sglang",
      }),
    ).toMatchObject({
      mode: "openai_compatible",
      slmRuntime: "sglang",
      openaiApiBase: "http://sglang:30000/v1",
    });
  });

  it("returns defaults for empty env", () => {
    expect(parseLlmInfraFromEnv({})).toEqual(DEFAULT_LLM_INFRA);
  });
});

describe("serializeLlmInfraToEnv", () => {
  it("serializes frontier provider model spec", () => {
    expect(
      serializeLlmInfraToEnv({
        mode: "frontier",
        frontierProvider: "google",
        modelId: "gemini-2.0-flash",
        openaiApiBase: "",
        slmRuntime: "vllm",
      }),
    ).toEqual({
      DEFAULT_LLM_MODEL: "google:gemini-2.0-flash",
      OPENAI_API_BASE: "",
      LLM_RUNTIME: "",
    });
  });

  it("serializes self-hosted openai-compatible config", () => {
    expect(
      serializeLlmInfraToEnv({
        mode: "openai_compatible",
        frontierProvider: "openai",
        modelId: "meta-llama/Llama-3.1-8B-Instruct",
        openaiApiBase: "http://vllm:8000/v1",
        slmRuntime: "vllm",
      }),
    ).toEqual({
      DEFAULT_LLM_MODEL: "openai:meta-llama/Llama-3.1-8B-Instruct",
      OPENAI_API_BASE: "http://vllm:8000/v1",
      LLM_RUNTIME: "vllm",
    });
  });

  it("clears self-hosted env when switching to frontier", () => {
    expect(
      serializeLlmInfraToEnv({
        mode: "frontier",
        frontierProvider: "openai",
        modelId: "gpt-4o-mini",
        openaiApiBase: "http://old-vllm:8000/v1",
        slmRuntime: "sglang",
      }),
    ).toEqual({
      DEFAULT_LLM_MODEL: "openai:gpt-4o-mini",
      OPENAI_API_BASE: "",
      LLM_RUNTIME: "",
    });
  });
});
