import { useMemo } from "react";
import { useLlmPresets } from "../hooks/useLlmPresets";
import { frontierProviderLabel } from "../lib/llmInfra";
import type { FrontierProvider } from "../lib/llmInfra";
import {
  DEFAULT_HERMES_MODEL_FORM,
  formatContextTokens,
  formatHermesModelValue,
  HERMES_MIN_CONTEXT_TOKENS,
  isHermesCompatibleContext,
  parseHermesModelValue,
  presetSpecLabel,
  type HermesModelFormState,
  type HermesModelSource,
} from "../lib/hermesModel";
import { formInputClassName } from "./FormPageLayout";

interface Props {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

const SOURCE_OPTIONS: {
  id: HermesModelSource;
  label: string;
  description: string;
}[] = [
  {
    id: "platform",
    label: "플랫폼 기본",
    description: "Infra Meta의 Default preset을 따릅니다.",
  },
  {
    id: "preset",
    label: "등록된 Preset",
    description: "preset:NAME 형식 — 예: preset:CLAUDE_SONNET",
  },
  {
    id: "explicit",
    label: "모델 직접 지정",
    description: "provider:model_id — 예: anthropic:claude-sonnet-4-6",
  },
];

const FRONTIER_PROVIDERS: FrontierProvider[] = ["openai", "anthropic", "google"];

const EXPLICIT_PLACEHOLDERS: Record<FrontierProvider, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-6",
  google: "gemini-2.0-flash",
};

export function HermesModelField({ value, onChange, disabled = false }: Props) {
  const { data: presets, isLoading, isError } = useLlmPresets();
  const form = useMemo(() => parseHermesModelValue(value), [value]);

  const defaultPreset = presets?.find((p) => p.is_default) ?? null;
  const sortedPresets = useMemo(() => {
    if (!presets) return [];
    return [...presets].sort((a, b) => {
      const aOk = isHermesCompatibleContext(a.context_window_tokens);
      const bOk = isHermesCompatibleContext(b.context_window_tokens);
      if (aOk !== bOk) return aOk ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [presets]);

  const selectedPreset =
    form.source === "preset"
      ? presets?.find((p) => p.name === form.presetName) ?? null
      : null;

  function emit(next: HermesModelFormState) {
    onChange(formatHermesModelValue(next));
  }

  function patch(partial: Partial<HermesModelFormState>) {
    emit({ ...form, ...partial });
  }

  function setSource(source: HermesModelSource) {
    if (source === form.source) return;
    if (source === "platform") {
      emit({ ...DEFAULT_HERMES_MODEL_FORM, source: "platform" });
      return;
    }
    if (source === "preset") {
      const firstCompatible =
        sortedPresets.find((p) => isHermesCompatibleContext(p.context_window_tokens)) ??
        sortedPresets[0];
      emit({
        ...DEFAULT_HERMES_MODEL_FORM,
        source: "preset",
        presetName: firstCompatible?.name ?? "",
      });
      return;
    }
    emit({
      ...DEFAULT_HERMES_MODEL_FORM,
      source: "explicit",
      provider: "anthropic",
      modelId: "claude-sonnet-4-6",
    });
  }

  const platformWarning =
    form.source === "platform" &&
    defaultPreset &&
    !isHermesCompatibleContext(defaultPreset.context_window_tokens);

  const presetWarning =
    form.source === "preset" &&
    selectedPreset &&
    !isHermesCompatibleContext(selectedPreset.context_window_tokens);

  const storedValue = formatHermesModelValue(form);

  return (
    <div className="space-y-3">
      <fieldset className="space-y-2" disabled={disabled}>
        <legend className="text-sm font-medium text-gray-700">LLM 모델</legend>
        <div className="space-y-2">
          {SOURCE_OPTIONS.map((opt) => (
            <label
              key={opt.id}
              className="flex items-start gap-2 rounded border border-gray-200 p-3 cursor-pointer has-checked:border-blue-500 has-checked:bg-blue-50/40"
            >
              <input
                type="radio"
                name="hermes-model-source"
                checked={form.source === opt.id}
                onChange={() => setSource(opt.id)}
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

      {form.source === "platform" && (
        <div className="rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
          {isLoading ? (
            <span className="text-gray-500">Default preset 불러오는 중…</span>
          ) : defaultPreset ? (
            <>
              <span className="font-medium">{defaultPreset.name}</span>
              <span className="text-gray-500"> — {presetSpecLabel(defaultPreset)}</span>
              <span className="block text-xs text-gray-500 mt-1">
                Context {formatContextTokens(defaultPreset.context_window_tokens)} tokens
              </span>
            </>
          ) : isError ? (
            <span className="text-gray-500">플랫폼 기본 preset 정보를 불러오지 못했습니다.</span>
          ) : (
            <span className="text-gray-500">등록된 Default preset이 없습니다.</span>
          )}
        </div>
      )}

      {form.source === "preset" && (
        <label className="block space-y-1">
          <span className="text-sm font-medium text-gray-700">Preset</span>
          <select
            value={form.presetName}
            disabled={disabled || isLoading || !sortedPresets.length}
            onChange={(e) => patch({ presetName: e.target.value })}
            className={formInputClassName}
          >
            {!sortedPresets.length ? (
              <option value="">등록된 preset 없음</option>
            ) : (
              sortedPresets.map((preset) => {
                const compatible = isHermesCompatibleContext(preset.context_window_tokens);
                return (
                  <option key={preset.id} value={preset.name} disabled={!compatible}>
                    {preset.name} — {presetSpecLabel(preset)} (
                    {formatContextTokens(preset.context_window_tokens)})
                    {!compatible ? " · Hermes 미지원" : ""}
                  </option>
                );
              })
            )}
          </select>
          {selectedPreset && (
            <span className="text-xs text-gray-500 block">
              저장 값:{" "}
              <code className="bg-gray-100 px-1 rounded">preset:{selectedPreset.name}</code>
            </span>
          )}
        </label>
      )}

      {form.source === "explicit" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Provider</span>
            <select
              value={form.provider}
              disabled={disabled}
              onChange={(e) => patch({ provider: e.target.value as FrontierProvider })}
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
              value={form.modelId}
              disabled={disabled}
              onChange={(e) => patch({ modelId: e.target.value })}
              placeholder={EXPLICIT_PLACEHOLDERS[form.provider]}
              className={formInputClassName}
            />
            <span className="text-xs text-gray-500 block">
              저장 값:{" "}
              <code className="bg-gray-100 px-1 rounded">
                {form.provider}:{form.modelId || "…"}
              </code>
            </span>
          </label>
        </div>
      )}

      {(platformWarning || presetWarning) && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          Hermes Agent는 context window가 최소{" "}
          {formatContextTokens(HERMES_MIN_CONTEXT_TOKENS)} tokens 이상이어야 합니다. 16k SLM
          preset은 사용할 수 없습니다.
        </p>
      )}

      {storedValue && (
        <p className="text-xs text-gray-500">
          config: <code className="bg-gray-100 px-1 rounded">{storedValue}</code>
        </p>
      )}
    </div>
  );
}
