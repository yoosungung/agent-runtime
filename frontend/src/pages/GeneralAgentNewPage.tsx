import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useCreateGeneralAgent } from "../hooks/useSourceMeta";
import { useMyAccessResources } from "../hooks/useMyUserMeta";
import { JsonEditor } from "../components/JsonEditor";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formInputClassName,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";
import { GeneralAgentVisibilityField } from "../components/GeneralAgentVisibilityField";
import type { GeneralVisibility } from "../lib/generalVisibility";
import {
  createSubmitLabel,
  createSubmitPendingLabel,
  newPageTitle,
} from "../lib/uiLabels";

interface FormValues {
  name: string;
  version: string;
  system_prompt: string;
}

export function GeneralAgentNewPage() {
  const navigate = useNavigate();
  const [mcpServers, setMcpServers] = useState<string[]>([]);
  const [visibility, setVisibility] = useState<GeneralVisibility>("private");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [globalError, setGlobalError] = useState<string | null>(null);

  const { data: mcpAccess, isLoading: mcpLoading } = useMyAccessResources("mcp");
  const createMut = useCreateGeneralAgent();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      name: "",
      version: "v1",
      system_prompt: "",
    },
  });

  const availableMcp = mcpAccess?.items ?? [];

  function toggleMcp(name: string) {
    setMcpServers((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function onSubmit(values: FormValues) {
    setGlobalError(null);
    if (mcpServers.length === 0) {
      setGlobalError("MCP 서버를 하나 이상 선택하세요.");
      return;
    }
    try {
      const result = await createMut.mutateAsync({
        name: values.name,
        version: values.version,
        system_prompt: values.system_prompt,
        mcp_servers: mcpServers,
        visibility,
        config,
      });
      navigate(`/agents/${result.id}`);
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "등록 실패");
    }
  }

  return (
    <FormPageLayout
      title={newPageTitle("agent", "agent")}
      description={
        <>
          Config-only agent — system prompt + MCP tools. VFS paths{" "}
          <code className="text-xs bg-gray-100 px-1 rounded">/</code>,{" "}
          <code className="text-xs bg-gray-100 px-1 rounded">/agent/</code>,{" "}
          <code className="text-xs bg-gray-100 px-1 rounded">/user/</code> are
          platform-fixed.
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name
            </label>
            <input
              {...register("name", {
                required: "Required",
                pattern: {
                  value: /^[a-z0-9][a-z0-9-]{0,127}$/,
                  message: "Lowercase alphanumeric and hyphens only",
                },
              })}
              className={formInputClassName}
            />
            {errors.name && (
              <p className="text-red-600 text-xs mt-1">{errors.name.message}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Version
            </label>
            <input
              {...register("version", { required: "Required" })}
              className={formInputClassName}
            />
            {errors.version && (
              <p className="text-red-600 text-xs mt-1">{errors.version.message}</p>
            )}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            System prompt
          </label>
          <textarea
            {...register("system_prompt", { required: "Required" })}
            rows={8}
            className={`${formInputClassName} font-mono`}
            placeholder="You are a helpful research assistant..."
          />
          {errors.system_prompt && (
            <p className="text-red-600 text-xs mt-1">
              {errors.system_prompt.message}
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            MCP servers
          </label>
          {mcpLoading ? (
            <p className="text-sm text-gray-500">Loading MCP servers…</p>
          ) : availableMcp.length === 0 ? (
            <p className="text-sm text-gray-500">
              사용 가능한 MCP 서버가 없습니다. 관리자에게 access를 요청하거나{" "}
              <Link to="/me" className="text-blue-600 underline">
                My Profile
              </Link>
              에서 integrations를 확인하세요.
            </p>
          ) : (
            <div className="space-y-2 border border-gray-200 rounded p-3">
              {availableMcp.map((mcp) => (
                <label key={mcp.source_meta_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={mcpServers.includes(mcp.name)}
                    onChange={() => toggleMcp(mcp.name)}
                  />
                  <span className="font-medium">{mcp.name}</span>
                  <span className="text-gray-400 text-xs">{mcp.version}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <GeneralAgentVisibilityField
          value={visibility}
          onChange={setVisibility}
        />

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Extra config (langgraph, API keys, …)
          </label>
          <JsonEditor value={config} onChange={setConfig} />
        </div>

        {globalError && <FormError message={globalError} />}

        <FormActions>
          <button
            type="button"
            onClick={() => navigate("/agents")}
            className={formSecondaryButtonClassName}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting || createMut.isPending}
            className={formPrimaryButtonClassName}
          >
            {isSubmitting || createMut.isPending
              ? createSubmitPendingLabel("agent")
              : createSubmitLabel("agent")}
          </button>
        </FormActions>
      </form>
    </FormPageLayout>
  );
}
