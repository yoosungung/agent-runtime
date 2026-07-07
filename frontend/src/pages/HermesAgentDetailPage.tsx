import { useState } from "react";
import { Link, useNavigate, useParams, Navigate } from "react-router-dom";
import {
  useDeleteSourceMeta,
  usePatchHermesAgent,
  useRetireSourceMeta,
  useSourceMetaById,
} from "../hooks/useSourceMeta";
import { useMyAccessResources } from "../hooks/useMyUserMeta";
import { useSession } from "../hooks/useSession";
import { ConfirmDialog } from "../components/ConfirmDialog";
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
import { AccessList } from "../components/AccessList";
import { generalVisibilityLabel } from "../lib/generalVisibility";
import { canManageGeneralAgent } from "../lib/generalAgent";
import { parseSkillsInput, readHermesConfig } from "../lib/hermesAgent";
import type { GeneralVisibility } from "../lib/generalVisibility";
import { sourceMetaDetailPath } from "../lib/sourceMetaPaths";
import { isAdminRole } from "../lib/roles";
import { vfsAgentBrowserPath } from "../lib/vfsPaths";

export function HermesAgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const numId = Number(id);
  const navigate = useNavigate();
  const { data: session } = useSession();
  const { data: item, isLoading, isError } = useSourceMetaById(numId);
  const patchMut = usePatchHermesAgent(numId);
  const retireMut = useRetireSourceMeta(numId);
  const deleteMut = useDeleteSourceMeta(numId);
  const { data: mcpAccess, isLoading: mcpLoading } = useMyAccessResources("mcp");

  const [soul, setSoul] = useState("");
  const [model, setModel] = useState("");
  const [skillsRaw, setSkillsRaw] = useState("");
  const [mcpServers, setMcpServers] = useState<string[]>([]);
  const [visibility, setVisibility] = useState<GeneralVisibility>("private");
  const [editInit, setEditInit] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [retireDialog, setRetireDialog] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!editInit && item) {
    const hermes = readHermesConfig(item.config);
    setSoul(hermes.soul ?? "");
    setModel(hermes.model ?? "");
    setSkillsRaw((hermes.skills ?? []).join(", "));
    setMcpServers(hermes.mcp_servers ?? []);
    setVisibility((item.visibility as GeneralVisibility) ?? "private");
    setEditInit(true);
  }

  if (isLoading) {
    return <p className="p-4 text-sm text-gray-500">Loading...</p>;
  }
  if (isError || !item) {
    return <p className="p-4 text-sm text-red-500">Agent를 불러오지 못했습니다.</p>;
  }
  if (item.deploy_mode !== "hermes_general") {
    return <Navigate to={sourceMetaDetailPath(item)} replace />;
  }

  const canManage = canManageGeneralAgent(item, session);
  const showVfsLink = isAdminRole(session?.role ?? "user");
  const availableMcp = mcpAccess?.items ?? [];

  function toggleMcp(name: string) {
    setMcpServers((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function handleSave() {
    if (!canManage) return;
    setSaveError(null);
    setSaveSuccess(false);
    if (!soul.trim()) {
      setSaveError("Soul은 필수입니다.");
      return;
    }
    if (mcpServers.length === 0) {
      setSaveError("MCP 서버를 하나 이상 선택하세요.");
      return;
    }
    try {
      await patchMut.mutateAsync({
        soul: soul.trim(),
        mcp_servers: mcpServers,
        skills: parseSkillsInput(skillsRaw),
        model: model.trim(),
        visibility,
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
      setActionError(err instanceof Error ? err.message : "Retire 실패");
    }
  }

  async function handleDelete() {
    try {
      await deleteMut.mutateAsync();
      navigate("/agents/hermes", { replace: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete 실패");
      setDeleteDialog(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => navigate("/agents/hermes")}
          className="text-sm text-blue-600 hover:underline"
        >
          Hermes Agent
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
        title={`${item.name} profile`}
        description={
          <>
            v{item.version} · pool {item.runtime_pool} · 사용 권한:{" "}
            {generalVisibilityLabel(item.visibility)}
            {!canManage && (
              <span className="block text-amber-700 mt-1">
                조회 전용 — 수정은 만든 사람 또는 admin만 가능합니다.
              </span>
            )}
          </>
        }
      >
        <div className="space-y-5">
          <GeneralAgentVisibilityField
            value={visibility}
            onChange={setVisibility}
            disabled={!canManage || item.retired}
          />

          {visibility === "allowlist" && (
            <AccessList sourceMetaId={numId} kind="agent" name={item.name} />
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Soul (SOUL.md)
            </label>
            <textarea
              value={soul}
              onChange={(e) => setSoul(e.target.value)}
              rows={8}
              disabled={!canManage || item.retired}
              className={`${formInputClassName} font-mono`}
            />
          </div>

          <HermesModelField
            value={model}
            onChange={setModel}
            disabled={!canManage || item.retired}
          />

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Skills (comma-separated)
            </label>
            <input
              value={skillsRaw}
              onChange={(e) => setSkillsRaw(e.target.value)}
              disabled={!canManage || item.retired}
              className={formInputClassName}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              MCP servers
            </label>
            {mcpLoading ? (
              <p className="text-sm text-gray-500">Loading MCP servers…</p>
            ) : (
              <div className="space-y-2 border border-gray-200 rounded p-3">
                {availableMcp.map((mcp) => (
                  <label key={mcp.source_meta_id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={mcpServers.includes(mcp.name)}
                      onChange={() => toggleMcp(mcp.name)}
                      disabled={!canManage || item.retired}
                    />
                    <span className="font-medium">{mcp.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {(saveError || actionError) && (
            <FormError message={saveError ?? actionError ?? ""} />
          )}
          {saveSuccess && (
            <p className="text-sm text-green-700">저장되었습니다. VFS에 반영됩니다.</p>
          )}

          {canManage && !item.retired && (
            <FormActions>
              <button
                type="button"
                onClick={() => setRetireDialog(true)}
                className={formSecondaryButtonClassName}
              >
                Retire
              </button>
              <button
                type="button"
                onClick={() => setDeleteDialog(true)}
                className="px-4 py-2 text-sm font-medium text-red-700 border border-red-300 rounded hover:bg-red-50"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={patchMut.isPending}
                className={formPrimaryButtonClassName}
              >
                {patchMut.isPending ? "Saving…" : "Save"}
              </button>
            </FormActions>
          )}
        </div>
      </FormPageLayout>

      <ConfirmDialog
        open={retireDialog}
        title="Retire agent?"
        description={`${item.name} v${item.version}을(를) retire합니다.`}
        confirmLabel="Retire"
        onConfirm={handleRetire}
        onCancel={() => setRetireDialog(false)}
      />
      <ConfirmDialog
        open={deleteDialog}
        title="Delete agent?"
        description="Hard delete — dev/stage에서만 가능합니다."
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteDialog(false)}
      />
    </div>
  );
}
