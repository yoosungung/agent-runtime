/** Platform infra LLM form — maps to flat pool env vars (DEFAULT_LLM_MODEL, …). */

export type LlmMode = "frontier" | "openai_compatible";

export type FrontierProvider = "openai" | "anthropic" | "google";

export type SlmRuntime = "vllm" | "sglang";

export interface LlmInfraFormState {
  mode: LlmMode;
  frontierProvider: FrontierProvider;
  /** Model id without provider prefix (e.g. gpt-4o-mini, claude-sonnet-4-6). */
  modelId: string;
  /** OpenAI-compatible base URL for vLLM / SGLang (→ OPENAI_API_BASE). */
  openaiApiBase: string;
  slmRuntime: SlmRuntime;
}

export const DEFAULT_LLM_INFRA: LlmInfraFormState = {
  mode: "frontier",
  frontierProvider: "openai",
  modelId: "",
  openaiApiBase: "",
  slmRuntime: "vllm",
};

const FRONTIER_PROVIDERS = new Set<FrontierProvider>(["openai", "anthropic", "google"]);
const SLM_RUNTIMES = new Set<SlmRuntime>(["vllm", "sglang"]);

function splitModelSpec(spec: string): { provider: string; modelId: string } | null {
  const trimmed = spec.trim();
  const idx = trimmed.indexOf(":");
  if (idx <= 0 || idx === trimmed.length - 1) return null;
  return {
    provider: trimmed.slice(0, idx),
    modelId: trimmed.slice(idx + 1),
  };
}

export function parseLlmInfraFromEnv(env: Record<string, string>): LlmInfraFormState {
  const baseUrl = (env.OPENAI_API_BASE ?? "").trim();
  const modelSpec = (env.DEFAULT_LLM_MODEL ?? "").trim();
  const runtimeRaw = (env.LLM_RUNTIME ?? "").trim();

  if (baseUrl) {
    const parsed = splitModelSpec(modelSpec);
    return {
      mode: "openai_compatible",
      frontierProvider: "openai",
      modelId: parsed?.modelId ?? modelSpec,
      openaiApiBase: baseUrl,
      slmRuntime: SLM_RUNTIMES.has(runtimeRaw as SlmRuntime)
        ? (runtimeRaw as SlmRuntime)
        : "vllm",
    };
  }

  const parsed = splitModelSpec(modelSpec);
  if (parsed && FRONTIER_PROVIDERS.has(parsed.provider as FrontierProvider)) {
    return {
      mode: "frontier",
      frontierProvider: parsed.provider as FrontierProvider,
      modelId: parsed.modelId,
      openaiApiBase: "",
      slmRuntime: "vllm",
    };
  }

  if (modelSpec) {
    return {
      mode: "frontier",
      frontierProvider: "openai",
      modelId: modelSpec,
      openaiApiBase: "",
      slmRuntime: "vllm",
    };
  }

  return { ...DEFAULT_LLM_INFRA };
}

export function serializeLlmInfraToEnv(state: LlmInfraFormState): Record<string, string> {
  const modelId = state.modelId.trim();

  if (state.mode === "openai_compatible") {
    return {
      DEFAULT_LLM_MODEL: modelId ? `openai:${modelId}` : "",
      OPENAI_API_BASE: state.openaiApiBase.trim(),
      LLM_RUNTIME: state.slmRuntime,
    };
  }

  const provider = state.frontierProvider;
  return {
    DEFAULT_LLM_MODEL: modelId ? `${provider}:${modelId}` : "",
    OPENAI_API_BASE: "",
    LLM_RUNTIME: "",
  };
}

export function frontierProviderLabel(provider: FrontierProvider): string {
  switch (provider) {
    case "openai":
      return "OpenAI";
    case "anthropic":
      return "Anthropic";
    case "google":
      return "Google";
  }
}

export function slmRuntimeLabel(runtime: SlmRuntime): string {
  return runtime === "vllm" ? "vLLM" : "SGLang";
}

export function llmInfraEquals(a: LlmInfraFormState, b: LlmInfraFormState): boolean {
  return (
    a.mode === b.mode &&
    a.frontierProvider === b.frontierProvider &&
    a.modelId === b.modelId &&
    a.openaiApiBase === b.openaiApiBase &&
    a.slmRuntime === b.slmRuntime
  );
}
