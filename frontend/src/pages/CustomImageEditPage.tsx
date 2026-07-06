import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useCustomImageList,
  usePatchCustomImage,
  useRestartCustomImage,
} from "../hooks/useCustomImages";
import { EnvVarEditor } from "../components/EnvVarEditor";
import { JsonEditor } from "../components/JsonEditor";
import { McpKnowledgePolicyField } from "../components/McpKnowledgePolicyField";
import { GeneralAgentChatSelectableField } from "../components/GeneralAgentChatSelectableField";
import { GeneralAgentVisibilityField } from "../components/GeneralAgentVisibilityField";
import { AccessList } from "../components/AccessList";
import type { ResourceVisibility } from "../lib/generalVisibility";
import {
  readMcpKnowledgeRequiresProject,
  withMcpKnowledgeRequiresProject,
} from "../lib/mcpKnowledgePolicy";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";

interface Props {
  kind: "agent" | "mcp";
}

export function CustomImageEditPage({ kind }: Props) {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useCustomImageList(kind);
  const item = data?.find((row) => row.slug === slug && row.status === "active");

  const patchMut = usePatchCustomImage(kind, slug);
  const restartMut = useRestartCustomImage();

  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [env, setEnv] = useState<Record<string, string>>({});
  const [requiresKnowledgeProject, setRequiresKnowledgeProject] = useState(false);
  const [chatSelectable, setChatSelectable] = useState(true);
  const [visibility, setVisibility] = useState<ResourceVisibility>("private");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const backPath = kind === "agent" ? "/container/agents" : "/container/mcp";

  useEffect(() => {
    if (!item) return;
    setConfig(item.config ?? {});
    setEnv(item.env ?? {});
    setChatSelectable(item.chat_selectable ?? true);
    setVisibility((item.visibility as ResourceVisibility) ?? "private");
    if (kind === "mcp") {
      setRequiresKnowledgeProject(readMcpKnowledgeRequiresProject(item.config ?? {}));
    }
  }, [item, kind]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!item) return;
    try {
      setSubmitError(null);
      const patchConfig =
        kind === "mcp"
          ? withMcpKnowledgeRequiresProject(config, requiresKnowledgeProject)
          : config;
      await patchMut.mutateAsync({
        config: patchConfig,
        env,
        visibility,
        ...(kind === "agent" ? { chat_selectable: chatSelectable } : {}),
      });
      await restartMut.mutateAsync({ kind: item.kind, slug: item.slug });
      navigate(backPath);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSubmitError(msg);
    }
  }

  if (isLoading) {
    return (
      <FormPageLayout title="Edit deployment">
        <p className="text-sm text-gray-500">Loading...</p>
      </FormPageLayout>
    );
  }

  if (isError || !item) {
    return (
      <FormPageLayout title="Edit deployment">
        <p className="text-sm text-red-600">Image not found or not active.</p>
        <button
          type="button"
          onClick={() => navigate(backPath)}
          className={`${formSecondaryButtonClassName} mt-4`}
        >
          Back
        </button>
      </FormPageLayout>
    );
  }

  return (
    <FormPageLayout title={`Edit ${item.name} (${item.version})`}>
      <p className="text-sm text-gray-600 mb-4">
        Slug: <span className="font-mono">{item.slug}</span>
      </p>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Environment variables{" "}
            <span className="text-gray-400 font-normal">
              (injected into K8s Deployment on save)
            </span>
          </label>
          <EnvVarEditor value={env} onChange={setEnv} />
          <p className="text-xs text-gray-500 mt-1">
            Platform keys (RUNTIME_POOL, DEPLOY_API_URL, POD_*) cannot be set here.
          </p>
        </div>

        {kind === "mcp" && (
          <McpKnowledgePolicyField
            checked={requiresKnowledgeProject}
            onChange={setRequiresKnowledgeProject}
          />
        )}

        {kind === "agent" && (
          <GeneralAgentChatSelectableField
            checked={chatSelectable}
            onChange={setChatSelectable}
          />
        )}

        <GeneralAgentVisibilityField value={visibility} onChange={setVisibility} />

        {visibility === "allowlist" && (
          <AccessList sourceMetaId={item.id} kind={kind} name={item.name} />
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Default Config <span className="text-gray-400 font-normal">(JSON, max 16KB)</span>
          </label>
          <JsonEditor value={config} onChange={setConfig} />
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
            disabled={patchMut.isPending || restartMut.isPending}
            className={formPrimaryButtonClassName}
          >
            {patchMut.isPending || restartMut.isPending ? "Saving..." : "Save & restart"}
          </button>
        </FormActions>
      </form>
    </FormPageLayout>
  );
}
