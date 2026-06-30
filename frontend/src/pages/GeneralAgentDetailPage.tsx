import { useState } from "react";
import { Link, useNavigate, useParams, Navigate } from "react-router-dom";
import {
  useDeleteSourceMeta,
  usePatchGeneralAgent,
  useRetireSourceMeta,
  useSourceMetaById,
} from "../hooks/useSourceMeta";
import { useMyAccessResources } from "../hooks/useMyUserMeta";
import { useSession } from "../hooks/useSession";
import { GeneralAgentKnowledgeProjectsField } from "../components/GeneralAgentKnowledgeProjectsField";
import { GeneralAgentVisibilityField } from "../components/GeneralAgentVisibilityField";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { JsonEditor } from "../components/JsonEditor";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formInputClassName,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";
import type { GeneralVisibility } from "../lib/generalVisibility";
import { generalVisibilityLabel } from "../lib/generalVisibility";
import {
  canManageGeneralAgent,
  readGeneralConfig,
} from "../lib/generalAgent";
import { mcpSelectionRequiresKnowledge } from "../lib/knowledgePolicy";
import { sourceMetaDetailPath } from "../lib/sourceMetaPaths";
import { isAdminRole } from "../lib/roles";
import { vfsAgentBrowserPath } from "../lib/vfsPaths";

export function GeneralAgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const numId = Number(id);
  const navigate = useNavigate();
  const { data: session } = useSession();
  const { data: item, isLoading, isError } = useSourceMetaById(numId);
  const patchMut = usePatchGeneralAgent(numId);
  const retireMut = useRetireSourceMeta(numId);
  const deleteMut = useDeleteSourceMeta(numId);
  const { data: mcpAccess, isLoading: mcpLoading } = useMyAccessResources("mcp");

  const [systemPrompt, setSystemPrompt] = useState("");
  const [mcpServers, setMcpServers] = useState<string[]>([]);
  const [knowledgeProjectIds, setKnowledgeProjectIds] = useState<string[]>([]);
  const [visibility, setVisibility] = useState<GeneralVisibility>("private");
  const [extraConfig, setExtraConfig] = useState<Record<string, unknown>>({});
  const [editInit, setEditInit] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [retireDialog, setRetireDialog] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState(false);

  if (!editInit && item) {
    const general = readGeneralConfig(item.config);
    setSystemPrompt(general.system_prompt ?? "");
    setMcpServers(general.mcp_servers ?? []);
    setKnowledgeProjectIds(general.knowledge_project_ids ?? []);
    setVisibility((item.visibility as GeneralVisibility) ?? "private");
    const { general: _g, ...rest } = item.config;
    setExtraConfig(rest);
    setEditInit(true);
  }

  const canManage = item ? canManageGeneralAgent(item, session) : false;
  const showVfsLink = isAdminRole(session?.role ?? "user");
  const availableMcp = mcpAccess?.items ?? [];
  const knowledgeRequired = mcpSelectionRequiresKnowledge(mcpServers, availableMcp);

  function toggleMcp(name: string) {
    setMcpServers((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function handleSave() {
    if (!item || !canManage) return;
    setSaveError(null);
    setSaveSuccess(false);
    if (!systemPrompt.trim()) {
      setSaveError("System prompt는 필수입니다.");
      return;
    }
    if (mcpServers.length === 0) {
      setSaveError("MCP 서버를 하나 이상 선택하세요.");
      return;
    }
    if (knowledgeRequired && knowledgeProjectIds.length === 0) {
      setSaveError(
        "선택한 MCP 중 pipeline project binding이 필요한 서버가 있습니다.",
      );
      return;
    }
    try {
      await patchMut.mutateAsync({
        system_prompt: systemPrompt.trim(),
        mcp_servers: mcpServers,
        knowledge_project_ids: knowledgeProjectIds,
        visibility,
        config: extraConfig,
      });
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "저장 실패");
    }
  }

  async function handleRetire() {
    try {
      await retireMut.mutateAsync();
      setRetireDialog(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Retire 실패");
    }
  }

  async function handleDelete() {
    try {
      await deleteMut.mutateAsync();
      navigate("/agents", { replace: true });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Delete 실패");
      setDeleteDialog(false);
    }
  }

  if (isLoading) {
    return <p className="p-4 text-sm text-gray-500">Loading...</p>;
  }
  if (isError || !item) {
    return <p className="p-4 text-sm text-red-500">Agent를 불러오지 못했습니다.</p>;
  }
  if (item.deploy_mode !== "general") {
    return <Navigate to={sourceMetaDetailPath(item)} replace />;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => navigate("/agents")}
          className="text-sm text-blue-600 hover:underline"
        >
          Agent
        </button>
        <span className="text-gray-400">/</span>
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{item.name}</h1>
        {showVfsLink && (
          <Link
            to={vfsAgentBrowserPath(item.kind, item.name)}
            className="text-sm text-blue-600 hover:underline"
          >
            VFS 관리
          </Link>
        )}
        {item.retired && (
          <span className="bg-red-100 text-red-800 text-xs font-medium px-2 py-0.5 rounded">
            Retired
          </span>
        )}
      </div>
      <FormPageLayout
        title={`${item.name} settings`}
        description={
          <>
            v{item.version} · 사용 권한: {generalVisibilityLabel(item.visibility)}
            {!canManage && (
              <span className="block text-amber-700 mt-1">
                조회 전용 — 수정은 만든 사람 또는 admin만 가능합니다.
              </span>
            )}
          </>
        }
      >
      <div className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            System prompt
          </label>
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={8}
            disabled={!canManage}
            className={`${formInputClassName} font-mono`}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            MCP servers
          </label>
          {mcpLoading ? (
            <p className="text-sm text-gray-500">Loading MCP servers…</p>
          ) : availableMcp.length === 0 ? (
            <p className="text-sm text-gray-500">사용 가능한 MCP 서버가 없습니다.</p>
          ) : (
            <div className="space-y-2 border border-gray-200 rounded p-3">
              {availableMcp.map((mcp) => (
                <label key={mcp.source_meta_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={mcpServers.includes(mcp.name)}
                    disabled={!canManage}
                    onChange={() => toggleMcp(mcp.name)}
                  />
                  <span className="font-medium">{mcp.name}</span>
                  <span className="text-gray-400 text-xs">{mcp.version}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <GeneralAgentKnowledgeProjectsField
          selectedIds={knowledgeProjectIds}
          onChange={setKnowledgeProjectIds}
          disabled={!canManage}
        />

        <GeneralAgentVisibilityField
          value={visibility}
          onChange={setVisibility}
          disabled={!canManage}
        />

        {canManage && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Extra config (langgraph, API keys, …)
            </label>
            <JsonEditor value={extraConfig} onChange={setExtraConfig} />
          </div>
        )}

        {saveError && <FormError message={saveError} />}
        {saveSuccess && (
          <p className="text-sm text-green-600 bg-green-50 border border-green-200 rounded px-3 py-2">
            저장되었습니다.
          </p>
        )}

        {canManage && (
          <FormActions>
            <button
              type="button"
              onClick={() => navigate("/agents")}
              className={formSecondaryButtonClassName}
            >
              Back
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={patchMut.isPending}
              className={formPrimaryButtonClassName}
            >
              {patchMut.isPending ? "Saving..." : "Save"}
            </button>
            {!item.retired && (
              <button
                type="button"
                onClick={() => setRetireDialog(true)}
                className="px-4 py-2 text-sm border border-amber-300 text-amber-800 rounded hover:bg-amber-50"
              >
                Retire
              </button>
            )}
            <button
              type="button"
              onClick={() => setDeleteDialog(true)}
              className="px-4 py-2 text-sm border border-red-300 text-red-700 rounded hover:bg-red-50"
            >
              Delete
            </button>
          </FormActions>
        )}
      </div>

      <ConfirmDialog
        open={retireDialog}
        title="Retire agent?"
        description="Retired agents cannot be invoked. Continue?"
        confirmLabel="Retire"
        onConfirm={handleRetire}
        onCancel={() => setRetireDialog(false)}
      />
      <ConfirmDialog
        open={deleteDialog}
        title="Delete agent?"
        description="This permanently removes the agent metadata."
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteDialog(false)}
      />
    </FormPageLayout>
    </div>
  );
}
