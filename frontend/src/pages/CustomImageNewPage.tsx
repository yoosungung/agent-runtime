import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateCustomImage, type CustomImageCreateBody } from "../hooks/useCustomImages";
import { JsonEditor } from "../components/JsonEditor";

interface Props {
  kind: "agent" | "mcp";
}

export function CustomImageNewPage({ kind }: Props) {
  const navigate = useNavigate();
  const createMut = useCreateCustomImage();

  const [form, setForm] = useState<CustomImageCreateBody>({
    kind,
    name: "",
    version: "",
    image_uri: "",
    image_digest: "",
    slug: "",
    replicas_max: 5,
    config: {},
    image_pull_secret: "",
  });
  const [configStr, setConfigStr] = useState("{}");
  const [configError, setConfigError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const backPath = kind === "agent" ? "/custom-agents" : "/custom-mcp";
  const title = kind === "agent" ? "Register Custom Agent Image" : "Register Custom MCP Image";

  function handleConfigChange(val: string) {
    setConfigStr(val);
    try {
      JSON.parse(val);
      setConfigError(null);
    } catch {
      setConfigError("Invalid JSON");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (configError) return;

    let config: Record<string, unknown> = {};
    try {
      config = JSON.parse(configStr);
    } catch {
      setConfigError("Invalid JSON");
      return;
    }

    const body: CustomImageCreateBody = {
      kind: form.kind,
      name: form.name.trim(),
      version: form.version.trim(),
      image_uri: form.image_uri.trim(),
      config,
    };
    if (form.image_digest?.trim()) body.image_digest = form.image_digest.trim();
    if (form.slug?.trim()) body.slug = form.slug.trim();
    if (form.replicas_max) body.replicas_max = form.replicas_max;
    if (form.image_pull_secret?.trim()) body.image_pull_secret = form.image_pull_secret.trim();

    try {
      setSubmitError(null);
      await createMut.mutateAsync(body);
      navigate(backPath);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSubmitError(msg);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">{title}</h1>
      <form onSubmit={handleSubmit} className="bg-white shadow rounded-lg p-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              pattern="^[a-z0-9][a-z0-9-]{0,127}$"
              title="lowercase letters, numbers, hyphens"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="my-agent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Version *</label>
            <input
              required
              value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="v1.0.0"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Image URI *</label>
          <input
            required
            value={form.image_uri}
            onChange={(e) => setForm({ ...form, image_uri: e.target.value })}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="registry.example.com/my-agent:v1.0.0"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Image Digest <span className="text-gray-400 font-normal">(optional, sha256:...)</span>
          </label>
          <input
            value={form.image_digest ?? ""}
            onChange={(e) => setForm({ ...form, image_digest: e.target.value })}
            pattern="(^$|^sha256:[0-9a-f]{64}$)"
            title="sha256:... hex digest or leave empty"
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="sha256:abc123..."
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Slug <span className="text-gray-400 font-normal">(auto-derived if empty)</span>
            </label>
            <input
              value={form.slug ?? ""}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              pattern="(^$|^[a-z0-9]([a-z0-9-]*[a-z0-9])?$)"
              maxLength={45}
              title="lowercase letters, numbers, hyphens, ≤ 45 chars"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="my-agent-v1-0-0"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Max Replicas
            </label>
            <input
              type="number"
              min={1}
              max={100}
              value={form.replicas_max ?? 5}
              onChange={(e) => setForm({ ...form, replicas_max: Number(e.target.value) })}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Image Pull Secret <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            value={form.image_pull_secret ?? ""}
            onChange={(e) => setForm({ ...form, image_pull_secret: e.target.value })}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="registry-creds"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Default Config <span className="text-gray-400 font-normal">(JSON, max 16KB)</span>
          </label>
          <JsonEditor value={configStr} onChange={handleConfigChange} rows={6} />
          {configError && (
            <p className="text-xs text-red-500 mt-1">{configError}</p>
          )}
        </div>

        {submitError && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
            {submitError}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => navigate(backPath)}
            className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium disabled:opacity-50"
          >
            {createMut.isPending ? "Deploying..." : "Deploy Image"}
          </button>
        </div>
      </form>
    </div>
  );
}
