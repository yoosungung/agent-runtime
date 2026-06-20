import type { LlmInfraFormState, LlmMode, SlmRuntime, FrontierProvider } from "../lib/llmInfra";
import { frontierProviderLabel, slmRuntimeLabel } from "../lib/llmInfra";
import { formInputClassName } from "./FormPageLayout";

interface Props {
  value: LlmInfraFormState;
  onChange: (value: LlmInfraFormState) => void;
}

const MODE_OPTIONS: { id: LlmMode; label: string; description: string }[] = [
  {
    id: "frontier",
    label: "Frontier (cloud API)",
    description: "OpenAI, Anthropic, Google — API keys below.",
  },
  {
    id: "openai_compatible",
    label: "Self-hosted (vLLM / SGLang)",
    description: "OpenAI-compatible endpoint — base URL + model id.",
  },
];

const FRONTIER_PROVIDERS: FrontierProvider[] = ["openai", "anthropic", "google"];
const SLM_RUNTIMES: SlmRuntime[] = ["vllm", "sglang"];

export function LlmDefaultsEditor({ value, onChange }: Props) {
  function patch(partial: Partial<LlmInfraFormState>) {
    onChange({ ...value, ...partial });
  }

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-gray-700">Provider type</legend>
        <div className="space-y-2">
          {MODE_OPTIONS.map((opt) => (
            <label
              key={opt.id}
              className="flex items-start gap-2 rounded border border-gray-200 p-3 cursor-pointer has-checked:border-blue-500 has-checked:bg-blue-50/40"
            >
              <input
                type="radio"
                name="llm-mode"
                checked={value.mode === opt.id}
                onChange={() => patch({ mode: opt.id })}
                className="mt-0.5"
              />
              <span>
                <span className="block text-sm font-medium text-gray-900">{opt.label}</span>
                <span className="block text-xs text-gray-500">{opt.description}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {value.mode === "frontier" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Provider</span>
            <select
              value={value.frontierProvider}
              onChange={(e) =>
                patch({ frontierProvider: e.target.value as FrontierProvider })
              }
              className={formInputClassName}
            >
              {FRONTIER_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {frontierProviderLabel(p)}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 sm:col-span-2">
            <span className="text-sm font-medium text-gray-700">Model ID</span>
            <input
              type="text"
              value={value.modelId}
              onChange={(e) => patch({ modelId: e.target.value })}
              placeholder={
                value.frontierProvider === "openai"
                  ? "gpt-4o-mini"
                  : value.frontierProvider === "anthropic"
                    ? "claude-sonnet-4-6"
                    : "gemini-2.0-flash"
              }
              className={formInputClassName}
            />
            <span className="text-xs text-gray-500">
              Stored as{" "}
              <code className="bg-gray-100 px-1 rounded">
                {value.frontierProvider}:{value.modelId || "…"}
              </code>
            </span>
          </label>
        </div>
      ) : (
        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Runtime</span>
            <select
              value={value.slmRuntime}
              onChange={(e) => patch({ slmRuntime: e.target.value as SlmRuntime })}
              className={formInputClassName}
            >
              {SLM_RUNTIMES.map((r) => (
                <option key={r} value={r}>
                  {slmRuntimeLabel(r)}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Base URL</span>
            <input
              type="url"
              value={value.openaiApiBase}
              onChange={(e) => patch({ openaiApiBase: e.target.value })}
              placeholder={
                value.slmRuntime === "vllm"
                  ? "http://vllm:8000/v1"
                  : "http://sglang:30000/v1"
              }
              className={formInputClassName}
            />
            <span className="text-xs text-gray-500">
              Pool env <code className="bg-gray-100 px-1 rounded">OPENAI_API_BASE</code> — LangChain /
              LiteLLM OpenAI-compatible routing.
            </span>
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Model ID</span>
            <input
              type="text"
              value={value.modelId}
              onChange={(e) => patch({ modelId: e.target.value })}
              placeholder="meta-llama/Llama-3.1-8B-Instruct"
              className={formInputClassName}
            />
            <span className="text-xs text-gray-500">
              Must match the model name served by {slmRuntimeLabel(value.slmRuntime)} (
              <code className="bg-gray-100 px-1 rounded">openai:{value.modelId || "…"}</code>).
            </span>
          </label>
          <p className="text-xs text-gray-500">
            Optional: set <strong>OpenAI API Key</strong> below if the server requires auth (many
            vLLM/SGLang deployments accept any non-empty key).
          </p>
        </div>
      )}
    </div>
  );
}
