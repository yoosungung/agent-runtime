import { useEffect, useState } from "react";
import {
  INFRA_UI_ENV_KEYS,
  INFRA_UI_SECRET_KEYS,
  useInfraMeta,
  useUpsertInfraMeta,
} from "../hooks/useInfraMeta";
import {
  useLlmPresets,
  useCreateLlmPreset,
  useUpdateLlmPreset,
  useDeleteLlmPreset,
  type LlmPreset,
} from "../hooks/useLlmPresets";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formPrimaryButtonClassName,
} from "../components/FormPageLayout";
import { LlmDefaultsEditor } from "../components/LlmDefaultsEditor";
import { frontierProviderLabel, slmRuntimeLabel, type LlmInfraFormState } from "../lib/llmInfra";

const SECRET_LABELS: Record<(typeof INFRA_UI_SECRET_KEYS)[number], string> = {
  OPENAI_API_KEY: "OpenAI API Key",
  ANTHROPIC_API_KEY: "Anthropic API Key",
  GOOGLE_API_KEY: "Google API Key",
  OPIK_API_KEY: "Opik API Key",
};

type TabId = "observability" | "presets" | "keys";

export function InfraMetaPage() {
  const { data: infraData, isLoading: isInfraLoading, isError: isInfraError } = useInfraMeta();
  const upsertInfraMut = useUpsertInfraMeta();

  const { data: presets, isLoading: isPresetsLoading } = useLlmPresets();
  const createPresetMut = useCreateLlmPreset();
  const updatePresetMut = useUpdateLlmPreset();
  const deletePresetMut = useDeleteLlmPreset();

  const [activeTab, setActiveTab] = useState<TabId>("observability");

  // General/Observability state
  const [opikUrl, setOpikUrl] = useState("");
  const [opikWorkspace, setOpikWorkspace] = useState("default");
  const [otlpEndpoint, setOtlpEndpoint] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Global Keys state
  const [globalSecrets, setGlobalSecrets] = useState<Record<string, string>>({});

  // Preset Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPreset, setEditingPreset] = useState<LlmPreset | null>(null);
  const [presetName, setPresetName] = useState("");
  const [presetDescription, setPresetDescription] = useState("");
  const [presetLlmConfig, setPresetLlmConfig] = useState<LlmInfraFormState>({
    mode: "frontier",
    frontierProvider: "openai",
    modelId: "",
    openaiApiBase: "",
    slmRuntime: "vllm",
  });
  const [presetApiKey, setPresetApiKey] = useState("");
  const [presetContextWindow, setPresetContextWindow] = useState("131072");
  const [presetMaxOutputTokens, setPresetMaxOutputTokens] = useState("");
  const [presetIsDefault, setPresetIsDefault] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  useEffect(() => {
    if (!infraData) return;
    const env = infraData.env ?? {};
    setOpikUrl(env[INFRA_UI_ENV_KEYS.opikUrl] ?? "");
    setOpikWorkspace(env[INFRA_UI_ENV_KEYS.opikWorkspace] ?? "default");
    setOtlpEndpoint(env[INFRA_UI_ENV_KEYS.otlpEndpoint] ?? "");
  }, [infraData]);

  async function handleObservabilitySubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const env = {
      [INFRA_UI_ENV_KEYS.opikUrl]: opikUrl.trim(),
      [INFRA_UI_ENV_KEYS.opikWorkspace]: opikWorkspace.trim() || "default",
      [INFRA_UI_ENV_KEYS.otlpEndpoint]: otlpEndpoint.trim(),
    };
    try {
      await upsertInfraMut.mutateAsync({ env });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function handleGlobalKeysSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const secretsPayload = Object.fromEntries(
      Object.entries(globalSecrets).filter(([, v]) => v.trim() !== ""),
    );
    if (Object.keys(secretsPayload).length === 0) {
      setSubmitError("Please fill in at least one API key.");
      return;
    }
    try {
      await upsertInfraMut.mutateAsync({ secrets: secretsPayload });
      setGlobalSecrets({});
      alert("API keys updated successfully.");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Save failed");
    }
  }

  function openNewPresetModal() {
    setEditingPreset(null);
    setPresetName("");
    setPresetDescription("");
    setPresetLlmConfig({
      mode: "frontier",
      frontierProvider: "openai",
      modelId: "",
      openaiApiBase: "",
      slmRuntime: "vllm",
    });
    setPresetApiKey("");
    setPresetContextWindow("131072");
    setPresetMaxOutputTokens("");
    setPresetIsDefault(false);
    setModalError(null);
    setIsModalOpen(true);
  }

  function openEditPresetModal(p: LlmPreset) {
    setEditingPreset(p);
    setPresetName(p.name);
    setPresetDescription(p.description || "");
    setPresetLlmConfig({
      mode: p.mode,
      frontierProvider: p.frontier_provider || "openai",
      modelId: p.model_id,
      openaiApiBase: p.openai_api_base || "",
      slmRuntime: p.slm_runtime || "vllm",
    });
    setPresetApiKey("");
    setPresetContextWindow(String(p.context_window_tokens));
    setPresetMaxOutputTokens(p.max_output_tokens != null ? String(p.max_output_tokens) : "");
    setPresetIsDefault(p.is_default);
    setModalError(null);
    setIsModalOpen(true);
  }

  async function handlePresetSubmit(e: React.FormEvent) {
    e.preventDefault();
    setModalError(null);

    const nameUpper = presetName.trim().toUpperCase();
    if (!nameUpper) {
      setModalError("Preset name is required.");
      return;
    }
    if (!/^[A-Z][A-Z0-9_]*$/.test(nameUpper)) {
      setModalError("Preset name must start with a letter and contain only uppercase letters, numbers, and underscores.");
      return;
    }
    if (!presetLlmConfig.modelId.trim()) {
      setModalError("Model ID is required.");
      return;
    }
    const contextWindow = Number(presetContextWindow);
    if (!Number.isInteger(contextWindow) || contextWindow <= 0) {
      setModalError("Context window must be a positive integer.");
      return;
    }
    const maxOutputRaw = presetMaxOutputTokens.trim();
    const maxOutputTokens = maxOutputRaw ? Number(maxOutputRaw) : null;
    if (maxOutputTokens != null && (!Number.isInteger(maxOutputTokens) || maxOutputTokens <= 0)) {
      setModalError("Max output tokens must be a positive integer.");
      return;
    }

    try {
      if (editingPreset) {
        // Update
        await updatePresetMut.mutateAsync({
          id: editingPreset.id,
          data: {
            description: presetDescription.trim() || null,
            mode: presetLlmConfig.mode,
            frontier_provider: presetLlmConfig.mode === "frontier" ? presetLlmConfig.frontierProvider : null,
            model_id: presetLlmConfig.modelId.trim(),
            openai_api_base: presetLlmConfig.mode === "openai_compatible" ? presetLlmConfig.openaiApiBase.trim() : null,
            slm_runtime: presetLlmConfig.mode === "openai_compatible" ? presetLlmConfig.slmRuntime : null,
            is_default: presetIsDefault,
            api_key: presetApiKey.trim() || null,
            context_window_tokens: contextWindow,
            max_output_tokens: maxOutputTokens,
          },
        });
      } else {
        // Create
        await createPresetMut.mutateAsync({
          name: nameUpper,
          description: presetDescription.trim() || null,
          mode: presetLlmConfig.mode,
          frontier_provider: presetLlmConfig.mode === "frontier" ? presetLlmConfig.frontierProvider : null,
          model_id: presetLlmConfig.modelId.trim(),
          openai_api_base: presetLlmConfig.mode === "openai_compatible" ? presetLlmConfig.openaiApiBase.trim() : null,
          slm_runtime: presetLlmConfig.mode === "openai_compatible" ? presetLlmConfig.slmRuntime : null,
          is_default: presetIsDefault,
          api_key: presetApiKey.trim() || null,
          context_window_tokens: contextWindow,
          max_output_tokens: maxOutputTokens,
        });
      }
      setIsModalOpen(false);
    } catch (err) {
      setModalError(err instanceof Error ? err.message : "Preset save failed");
    }
  }

  async function handleToggleDefault(preset: LlmPreset) {
    if (preset.is_default) return; // Already default
    try {
      await updatePresetMut.mutateAsync({
        id: preset.id,
        data: {
          mode: preset.mode,
          frontier_provider: preset.frontier_provider,
          model_id: preset.model_id,
          openai_api_base: preset.openai_api_base,
          slm_runtime: preset.slm_runtime,
          is_default: true,
          context_window_tokens: preset.context_window_tokens,
          max_output_tokens: preset.max_output_tokens,
        },
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to toggle default preset");
    }
  }

  async function handleDeletePreset(preset: LlmPreset) {
    if (!confirm(`Are you sure you want to delete preset "${preset.name}"?`)) return;
    try {
      await deletePresetMut.mutateAsync(preset.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete preset");
    }
  }

  if (isInfraLoading || isPresetsLoading) {
    return <p className="text-gray-500 p-6">Loading settings…</p>;
  }
  if (isInfraError) {
    return <p className="text-red-600 p-6">Failed to load platform settings.</p>;
  }

  return (
    <FormPageLayout
      title="Platform Settings"
      description="Configure global platform options, observability tools, and manage LLM presets."
    >
      <div className="flex flex-col w-full min-h-0">
        {/* Navigation Tabs */}
        <div className="border-b border-gray-200 shrink-0">
          <nav className="-mb-px flex space-x-8" aria-label="Tabs">
            <button
              onClick={() => {
                setActiveTab("observability");
                setSubmitError(null);
              }}
              className={`pb-4 px-1 border-b-2 font-medium text-sm transition-all duration-200 ${
                activeTab === "observability"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              General & Observability
            </button>
            <button
              onClick={() => {
                setActiveTab("presets");
                setSubmitError(null);
              }}
              className={`pb-4 px-1 border-b-2 font-medium text-sm transition-all duration-200 ${
                activeTab === "presets"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              LLM Presets
            </button>
            <button
              onClick={() => {
                setActiveTab("keys");
                setSubmitError(null);
              }}
              className={`pb-4 px-1 border-b-2 font-medium text-sm transition-all duration-200 ${
                activeTab === "keys"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              Global API Keys
            </button>
          </nav>
        </div>

        {/* Tab Contents */}
        <div data-testid="platform-tab-panel" className="w-full flex-1 pt-6">
          {activeTab === "observability" && (
            <form onSubmit={handleObservabilitySubmit} className="space-y-6">
              <div className="space-y-4">
                <h2 className="text-lg font-semibold text-gray-900 border-b pb-2">Observability Settings</h2>
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-gray-700">Opik URL</span>
                  <input
                    type="url"
                    value={opikUrl}
                    onChange={(e) => setOpikUrl(e.target.value)}
                    placeholder="http://opik-frontend.example:5173/api"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-gray-700">Opik Workspace</span>
                  <input
                    type="text"
                    value={opikWorkspace}
                    onChange={(e) => setOpikWorkspace(e.target.value)}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-gray-700">OTLP Endpoint (pools)</span>
                  <input
                    type="text"
                    value={otlpEndpoint}
                    onChange={(e) => setOtlpEndpoint(e.target.value)}
                    placeholder="http://otel-collector:4317"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </label>
              </div>

              {submitError ? <FormError message={submitError} /> : null}

              <FormActions>
                <button
                  type="submit"
                  disabled={upsertInfraMut.isPending}
                  className={formPrimaryButtonClassName}
                >
                  {upsertInfraMut.isPending ? "Saving…" : "Save & Reconcile"}
                </button>
              </FormActions>
            </form>
          )}

          {activeTab === "presets" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center border-b pb-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">LLM Presets</h2>
                  <p className="text-xs text-gray-500">
                    Define reusable LLM configurations. Bundle configs can reference these presets via{" "}
                    <code className="bg-gray-100 px-1 rounded">preset:NAME</code>.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={openNewPresetModal}
                  className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
                >
                  Add Preset
                </button>
              </div>

              {/* Presets Table */}
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Default</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Name</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Type / Provider</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Model ID</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Configured Keys</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-gray-700 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-100">
                    {presets && presets.length > 0 ? (
                      presets.map((preset) => (
                        <tr key={preset.id} className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-3 whitespace-nowrap">
                            <input
                              type="radio"
                              name="default-preset"
                              checked={preset.is_default}
                              onChange={() => handleToggleDefault(preset)}
                              className="h-4 w-4 text-blue-600 border-gray-300 focus:ring-blue-500 cursor-pointer"
                            />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <span className="font-semibold text-gray-900 block">{preset.name}</span>
                            {preset.description && (
                              <span className="text-xs text-gray-500 block max-w-xs truncate">
                                {preset.description}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                            {preset.mode === "frontier" ? (
                              <span>Frontier ({frontierProviderLabel(preset.frontier_provider!)})</span>
                            ) : (
                              <span>Self-hosted ({slmRuntimeLabel(preset.slm_runtime!)})</span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                            {preset.model_id}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-xs">
                            {preset.api_key_configured ? (
                              <span className="bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-medium">
                                API Key Wired
                              </span>
                            ) : (
                              <span className="bg-gray-50 text-gray-500 border border-gray-200 px-2 py-0.5 rounded-full">
                                No Key
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-right text-sm font-medium space-x-2">
                            <button
                              type="button"
                              onClick={() => openEditPresetModal(preset)}
                              className="text-blue-600 hover:text-blue-800 transition-colors"
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeletePreset(preset)}
                              className="text-red-600 hover:text-red-800 transition-colors"
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                          No LLM presets created yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === "keys" && (
            <form onSubmit={handleGlobalKeysSubmit} className="space-y-6">
              <div className="space-y-4">
                <h2 className="text-lg font-semibold text-gray-900 border-b pb-2">Global API Keys</h2>
                <p className="text-sm text-gray-500">
                  Global keys stored securely inside the K8s Secret. Fill in values to set or update existing keys.
                </p>
                {INFRA_UI_SECRET_KEYS.map((key) => (
                  <label key={key} className="block space-y-1">
                    <span className="text-sm font-medium text-gray-700">
                      {SECRET_LABELS[key]}
                      {infraData?.secret_keys.includes(key) ? (
                        <span className="ml-2 text-xs text-green-700 font-semibold bg-green-50 px-2 py-0.5 rounded-full border border-green-200">
                          configured
                        </span>
                      ) : null}
                    </span>
                    <input
                      type="password"
                      autoComplete="off"
                      value={globalSecrets[key] ?? ""}
                      onChange={(e) =>
                        setGlobalSecrets((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      placeholder={
                        infraData?.secret_keys.includes(key)
                          ? "••••••••••••••••••••• (unchanged)"
                          : undefined
                      }
                      className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    />
                  </label>
                ))}
              </div>

              {submitError ? <FormError message={submitError} /> : null}

              <FormActions>
                <button
                  type="submit"
                  disabled={upsertInfraMut.isPending}
                  className={formPrimaryButtonClassName}
                >
                  {upsertInfraMut.isPending ? "Saving…" : "Save Keys"}
                </button>
              </FormActions>
            </form>
          )}
        </div>
      </div>

      {/* Preset Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-fade-in">
          <div className="bg-white w-full max-w-xl rounded-lg shadow-xl border border-gray-100 max-h-[90vh] flex flex-col">
            <div className="border-b px-6 py-4 flex justify-between items-center bg-gray-50 rounded-t-lg">
              <h3 className="text-base font-semibold text-gray-900">
                {editingPreset ? `Edit Preset: ${editingPreset.name}` : "Create New LLM Preset"}
              </h3>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-lg transition-colors"
              >
                &times;
              </button>
            </div>

            <form onSubmit={handlePresetSubmit} className="flex-1 overflow-y-auto p-6 space-y-6">
              <label className="block space-y-1">
                <span className="text-sm font-medium text-gray-700">Preset Name</span>
                <input
                  type="text"
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value.toUpperCase())}
                  disabled={!!editingPreset}
                  placeholder="MY_OPENAI_MODEL"
                  required
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-500"
                />
                <span className="text-xs text-gray-500 block">
                  Upper snake case only. Referenced as <code className="bg-gray-100 px-1 rounded">preset:{presetName || "NAME"}</code>.
                </span>
              </label>

              <label className="block space-y-1">
                <span className="text-sm font-medium text-gray-700">Description</span>
                <input
                  type="text"
                  value={presetDescription}
                  onChange={(e) => setPresetDescription(e.target.value)}
                  placeholder="Optional description"
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                />
              </label>

              {/* Reused LlmDefaultsEditor */}
              <div className="border-t border-b border-gray-100 py-4">
                <LlmDefaultsEditor
                  value={presetLlmConfig}
                  onChange={setPresetLlmConfig}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-gray-700">Context Window (tokens)</span>
                  <input
                    type="number"
                    min={1}
                    value={presetContextWindow}
                    onChange={(e) => setPresetContextWindow(e.target.value)}
                    required
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm font-medium text-gray-700">Max Output (tokens, optional)</span>
                  <input
                    type="number"
                    min={1}
                    value={presetMaxOutputTokens}
                    onChange={(e) => setPresetMaxOutputTokens(e.target.value)}
                    placeholder="e.g. 8192"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </label>
              </div>

              <label className="block space-y-1">
                <span className="text-sm font-medium text-gray-700">
                  Preset API Key
                  {editingPreset?.api_key_configured && (
                    <span className="ml-2 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full border border-green-200">
                      configured
                    </span>
                  )}
                </span>
                <input
                  type="password"
                  value={presetApiKey}
                  onChange={(e) => setPresetApiKey(e.target.value)}
                  placeholder={editingPreset?.api_key_configured ? "•••••••• (unchanged)" : "API Key for this preset"}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                />
              </label>

              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={presetIsDefault}
                  onChange={(e) => setPresetIsDefault(e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-gray-700">Set as platform default</span>
              </label>

              {modalError ? <FormError message={modalError} /> : null}

              <div className="border-t pt-4 flex justify-end gap-3 bg-white">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 border rounded text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createPresetMut.isPending || updatePresetMut.isPending}
                  className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
                >
                  {createPresetMut.isPending || updatePresetMut.isPending ? "Saving…" : "Save Preset"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </FormPageLayout>
  );
}
