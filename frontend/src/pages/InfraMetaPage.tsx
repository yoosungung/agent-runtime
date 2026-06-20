import { useEffect, useState } from "react";
import { useInfraMeta, useUpsertInfraMeta } from "../hooks/useInfraMeta";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formPrimaryButtonClassName,
} from "../components/FormPageLayout";

const SECRET_FIELDS = [
  { key: "OPENAI_API_KEY", label: "OpenAI API Key" },
  { key: "ANTHROPIC_API_KEY", label: "Anthropic API Key" },
  { key: "GOOGLE_API_KEY", label: "Google API Key" },
  { key: "OPIK_API_KEY", label: "Opik API Key" },
] as const;

export function InfraMetaPage() {
  const { data, isLoading, isError } = useInfraMeta();
  const upsertMut = useUpsertInfraMeta();

  const [opikUrl, setOpikUrl] = useState("");
  const [opikWorkspace, setOpikWorkspace] = useState("default");
  const [defaultModel, setDefaultModel] = useState("");
  const [otlpEndpoint, setOtlpEndpoint] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setOpikUrl(data.env.opik_url ?? "");
    setOpikWorkspace(data.env.opik_workspace ?? "default");
    setDefaultModel(data.env.default_llm_model ?? "");
    setOtlpEndpoint(data.env.otlp_endpoint ?? "");
    setSecrets({});
  }, [data]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const env: Record<string, string> = {};
    if (opikUrl.trim()) env.opik_url = opikUrl.trim();
    if (opikWorkspace.trim()) env.opik_workspace = opikWorkspace.trim();
    if (defaultModel.trim()) env.default_llm_model = defaultModel.trim();
    if (otlpEndpoint.trim()) env.otlp_endpoint = otlpEndpoint.trim();

    const secretsPayload = Object.fromEntries(
      Object.entries(secrets).filter(([, v]) => v.trim() !== ""),
    );

    try {
      const result = await upsertMut.mutateAsync({
        env,
        ...(Object.keys(secretsPayload).length > 0 ? { secrets: secretsPayload } : {}),
      });
      if (result.reconciled === false) {
        setSubmitError(
          "Saved to database but K8s reconcile failed — pool pods may need a manual restart.",
        );
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Save failed");
    }
  }

  if (isLoading) {
    return <p className="text-gray-500">Loading…</p>;
  }
  if (isError) {
    return <p className="text-red-600">Failed to load platform infra settings.</p>;
  }

  return (
    <FormPageLayout
      title="Platform Infra"
      description="Cluster-wide LLM keys, Opik, and observability settings injected into pool pod environment."
    >
      <form onSubmit={handleSubmit} className="space-y-8 max-w-2xl">
        <section className="space-y-4">
          <h2 className="text-lg font-medium text-gray-900">Observability</h2>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Opik URL</span>
            <input
              type="url"
              value={opikUrl}
              onChange={(e) => setOpikUrl(e.target.value)}
              placeholder="http://opik-frontend.example:5173/api"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Opik Workspace</span>
            <input
              type="text"
              value={opikWorkspace}
              onChange={(e) => setOpikWorkspace(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">OTLP Endpoint (pools)</span>
            <input
              type="text"
              value={otlpEndpoint}
              onChange={(e) => setOtlpEndpoint(e.target.value)}
              placeholder="http://otel-collector:4317"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
        </section>

        <section className="space-y-4">
          <h2 className="text-lg font-medium text-gray-900">LLM Defaults</h2>
          <label className="block space-y-1">
            <span className="text-sm font-medium text-gray-700">Default LLM Model</span>
            <input
              type="text"
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder="openai:gpt-4o-mini"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
        </section>

        <section className="space-y-4">
          <h2 className="text-lg font-medium text-gray-900">API Keys</h2>
          <p className="text-sm text-gray-500">
            Values are stored in K8s Secret only. Leave blank to keep existing keys.
          </p>
          {SECRET_FIELDS.map(({ key, label }) => (
            <label key={key} className="block space-y-1">
              <span className="text-sm font-medium text-gray-700">
                {label}
                {data?.secret_keys.includes(key) ? (
                  <span className="ml-2 text-xs text-green-700">(configured)</span>
                ) : null}
              </span>
              <input
                type="password"
                autoComplete="off"
                value={secrets[key] ?? ""}
                onChange={(e) =>
                  setSecrets((prev) => ({ ...prev, [key]: e.target.value }))
                }
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
          ))}
        </section>

        {submitError ? <FormError message={submitError} /> : null}

        <FormActions>
          <button
            type="submit"
            disabled={upsertMut.isPending}
            className={formPrimaryButtonClassName}
          >
            {upsertMut.isPending ? "Saving…" : "Save & Reconcile"}
          </button>
        </FormActions>
      </form>
    </FormPageLayout>
  );
}
