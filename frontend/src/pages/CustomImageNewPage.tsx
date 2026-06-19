import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateCustomImage, type CustomImageCreateBody } from "../hooks/useCustomImages";
import { JsonEditor } from "../components/JsonEditor";
import { EnvVarEditor } from "../components/EnvVarEditor";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formInputClassName,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";
import {
  deployImagePendingLabel,
  deployImageSubmitLabel,
  newPageTitle,
} from "../lib/uiLabels";

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
    env: {},
    image_pull_secret: "",
  });
  const [submitError, setSubmitError] = useState<string | null>(null);

  const backPath = kind === "agent" ? "/container/agents" : "/container/mcp";
  const title = newPageTitle("container", kind);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const body: CustomImageCreateBody = {
      kind: form.kind,
      name: form.name.trim(),
      version: form.version.trim(),
      image_uri: form.image_uri.trim(),
      config: form.config,
    };
    if (form.env && Object.keys(form.env).length > 0) body.env = form.env;
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
    <FormPageLayout title={title}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              pattern="^[a-z0-9][a-z0-9-]{0,127}$"
              title="lowercase letters, numbers, hyphens"
              className={formInputClassName}
              placeholder="my-agent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Version *</label>
            <input
              required
              value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
              className={formInputClassName}
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
            className={formInputClassName}
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
            className={`${formInputClassName} font-mono`}
            placeholder="sha256:abc123..."
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
              className={`${formInputClassName} font-mono`}
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
              className={formInputClassName}
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
            className={formInputClassName}
            placeholder="registry-creds"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Environment variables{" "}
            <span className="text-gray-400 font-normal">(optional, K8s Deployment env)</span>
          </label>
          <EnvVarEditor
            value={form.env ?? {}}
            onChange={(env) => setForm({ ...form, env })}
          />
          <p className="text-xs text-gray-500 mt-1">
            Pod startup env (e.g. LOG_LEVEL). Default Config below is passed per invoke via
            x-runtime-cfg.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Default Config <span className="text-gray-400 font-normal">(JSON, max 16KB)</span>
          </label>
          <JsonEditor
            value={form.config ?? {}}
            onChange={(val) => setForm({ ...form, config: val })}
          />
        </div>

        {submitError && <FormError message={submitError} />}

        <FormActions>
          <button
            type="button"
            onClick={() => navigate(backPath)}
            className={formSecondaryButtonClassName}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMut.isPending}
            className={formPrimaryButtonClassName}
          >
            {createMut.isPending ? deployImagePendingLabel : deployImageSubmitLabel}
          </button>
        </FormActions>
      </form>
    </FormPageLayout>
  );
}
