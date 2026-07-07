import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Controller, useForm } from "react-hook-form";
import { useCreateHermesAgent } from "../hooks/useSourceMeta";
import { useMyAccessResources } from "../hooks/useMyUserMeta";
import { JsonEditor } from "../components/JsonEditor";
import { AgentTierNav } from "../components/AgentTierNav";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formInputClassName,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";
import { GeneralAgentVisibilityField } from "../components/GeneralAgentVisibilityField";
import { HermesModelField } from "../components/HermesModelField";
import type { GeneralVisibility } from "../lib/generalVisibility";
import { parseSkillsInput } from "../lib/hermesAgent";
import {
  createSubmitLabel,
  createSubmitPendingLabel,
  newPageTitle,
} from "../lib/uiLabels";

interface FormValues {
  name: string;
  version: string;
  soul: string;
  model: string;
  skills: string;
}

export function HermesAgentNewPage() {
  const navigate = useNavigate();
  const [mcpServers, setMcpServers] = useState<string[]>([]);
  const [visibility, setVisibility] = useState<GeneralVisibility>("private");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [globalError, setGlobalError] = useState<string | null>(null);

  const { data: mcpAccess, isLoading: mcpLoading } = useMyAccessResources("mcp");
  const createMut = useCreateHermesAgent();

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      name: "",
      version: "v1",
      soul: "",
      model: "",
      skills: "",
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
        soul: values.soul,
        mcp_servers: mcpServers,
        skills: parseSkillsInput(values.skills),
        model: values.model.trim(),
        visibility,
        config,
      });
      navigate(`/agents/hermes/${result.id}`);
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "등록 실패");
    }
  }

  return (
    <>
      <AgentTierNav />
      <FormPageLayout
        title={newPageTitle("hermes", "agent")}
        description={
          <>
            Hermes profile agent — soul + MCP + skills. VFS paths{" "}
            <code className="text-xs bg-gray-100 px-1 rounded">/profile/SOUL.md</code>,{" "}
            <code className="text-xs bg-gray-100 px-1 rounded">/profile/config.yaml</code>,{" "}
            <code className="text-xs bg-gray-100 px-1 rounded">/profile/skills/</code> 에 seed
            됩니다.
          </>
        }
      >
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
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

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="hermes-agent-version"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Version
              </label>
              <input
                id="hermes-agent-version"
                {...register("version", { required: "Required" })}
                className={formInputClassName}
              />
              {errors.version && (
                <p className="text-red-600 text-xs mt-1">{errors.version.message}</p>
              )}
            </div>

            <GeneralAgentVisibilityField
              value={visibility}
              onChange={setVisibility}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Soul (SOUL.md)
            </label>
            <textarea
              {...register("soul", { required: "Required" })}
              rows={8}
              className={`${formInputClassName} font-mono`}
              placeholder="You are a helpful assistant with long-term memory..."
            />
            {errors.soul && (
              <p className="text-red-600 text-xs mt-1">{errors.soul.message}</p>
            )}
          </div>

          <Controller
            name="model"
            control={control}
            render={({ field }) => (
              <HermesModelField value={field.value} onChange={field.onChange} />
            )}
          />

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Skills (optional, comma-separated)
            </label>
            <input
              {...register("skills")}
              className={formInputClassName}
              placeholder="plan, search"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              MCP servers
            </label>
            {mcpLoading ? (
              <p className="text-sm text-gray-500">Loading MCP servers…</p>
            ) : availableMcp.length === 0 ? (
              <p className="text-sm text-gray-500">
                사용 가능한 MCP 서버가 없습니다.{" "}
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

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Extra config (optional)
            </label>
            <JsonEditor value={config} onChange={setConfig} />
          </div>

          {globalError && <FormError message={globalError} />}

          <FormActions>
            <button
              type="button"
              onClick={() => navigate("/agents/hermes")}
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
    </>
  );
}
