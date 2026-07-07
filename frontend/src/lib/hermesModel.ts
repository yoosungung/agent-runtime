/** Hermes agent model field — maps UI state to `hermes.model` config string. */

import type { FrontierProvider } from "./llmInfra";
import type { LlmPreset } from "../hooks/useLlmPresets";

export const HERMES_MIN_CONTEXT_TOKENS = 65_536;

export type HermesModelSource = "platform" | "preset" | "explicit";

export interface HermesModelFormState {
  source: HermesModelSource;
  presetName: string;
  provider: FrontierProvider;
  modelId: string;
}

export const DEFAULT_HERMES_MODEL_FORM: HermesModelFormState = {
  source: "platform",
  presetName: "",
  provider: "anthropic",
  modelId: "",
};

const FRONTIER_PROVIDERS = new Set<FrontierProvider>(["openai", "anthropic", "google"]);

export function isHermesCompatibleContext(tokens: number): boolean {
  return tokens >= HERMES_MIN_CONTEXT_TOKENS;
}

export function parseHermesModelValue(raw: string): HermesModelFormState {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ...DEFAULT_HERMES_MODEL_FORM };
  }
  if (trimmed.startsWith("preset:")) {
    return {
      ...DEFAULT_HERMES_MODEL_FORM,
      source: "preset",
      presetName: trimmed.slice("preset:".length).trim(),
    };
  }
  const colon = trimmed.indexOf(":");
  if (colon > 0) {
    const provider = trimmed.slice(0, colon);
    const modelId = trimmed.slice(colon + 1);
    return {
      ...DEFAULT_HERMES_MODEL_FORM,
      source: "explicit",
      provider: FRONTIER_PROVIDERS.has(provider as FrontierProvider)
        ? (provider as FrontierProvider)
        : "openai",
      modelId,
    };
  }
  const slash = trimmed.indexOf("/");
  if (slash > 0) {
    const provider = trimmed.slice(0, slash);
    const modelId = trimmed.slice(slash + 1);
    return {
      ...DEFAULT_HERMES_MODEL_FORM,
      source: "explicit",
      provider: FRONTIER_PROVIDERS.has(provider as FrontierProvider)
        ? (provider as FrontierProvider)
        : "openai",
      modelId,
    };
  }
  return {
    ...DEFAULT_HERMES_MODEL_FORM,
    source: "explicit",
    modelId: trimmed,
  };
}

export function formatHermesModelValue(state: HermesModelFormState): string {
  if (state.source === "platform") {
    return "";
  }
  if (state.source === "preset") {
    return state.presetName.trim() ? `preset:${state.presetName.trim()}` : "";
  }
  const modelId = state.modelId.trim();
  if (!modelId) {
    return "";
  }
  return `${state.provider}:${modelId}`;
}

export function presetSpecLabel(preset: LlmPreset): string {
  if (preset.mode === "frontier" && preset.frontier_provider) {
    return `${preset.frontier_provider}:${preset.model_id}`;
  }
  return `openai:${preset.model_id}`;
}

export function formatContextTokens(tokens: number): string {
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(tokens % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (tokens >= 1_000) {
    return `${Math.round(tokens / 1_000)}k`;
  }
  return String(tokens);
}
