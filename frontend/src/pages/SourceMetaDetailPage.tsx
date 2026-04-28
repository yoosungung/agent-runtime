import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  useSourceMetaById,
  usePatchSourceMeta,
  useRetireSourceMeta,
  useDeleteSourceMeta,
  useVerifySourceMeta,
} from "../hooks/useSourceMeta";
import { getRuntimeKinds } from "../lib/enums";
import { JsonEditor } from "../components/JsonEditor";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { SignatureUploadDialog } from "../components/SignatureUploadDialog";
import { AccessList } from "../components/AccessList";
import { Paginator } from "../components/Paginator";
import { usePagination } from "../hooks/usePagination";
import { apiJson, type PageResponse } from "../lib/api";
import type { SourceMeta } from "../hooks/useSourceMeta";
import type { UserMeta } from "../hooks/useUserMeta";

interface Props {
  kind: "agent" | "mcp";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function SourceMetaDetailPage({ kind }: Props) {
  const { id } = useParams<{ id: string }>();
  const numId = Number(id);
  const navigate = useNavigate();
  const basePath = kind === "agent" ? "/agents" : "/mcp-servers";

  const { data: item, isLoading, isError } = useSourceMetaById(numId);
  const patchMut = usePatchSourceMeta(numId);
  const retireMut = useRetireSourceMeta(numId);
  const deleteMut = useDeleteSourceMeta(numId);
  const verifyMut = useVerifySourceMeta(numId);
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [activeTab, setActiveTab] = useState<"user-meta" | "access">(
    "user-meta",
  );

  // Editable fields
  const [entrypoint, setEntrypoint] = useState("");
  const [runtimePool, setRuntimePool] = useState("");
  const [sigUri, setSigUri] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [editInit, setEditInit] = useState(false);

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [retireDialog, setRetireDialog] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [sigDialog, setSigDialog] = useState(false);

  // User meta list
  const { limit: umLimit, offset: umOffset, setOffset: setUmOffset } = usePagination(20);
  const [userMetaItems, setUserMetaItems] = useState<UserMeta[]>([]);
  const [userMetaTotal, setUserMetaTotal] = useState(0);
  const [userMetaLoading, setUserMetaLoading] = useState(false);

  const runtimeKinds = getRuntimeKinds(kind);

  if (!editInit && item) {
    setEntrypoint(item.entrypoint);
    setRuntimePool(item.runtime_pool);
    setSigUri(item.sig_uri ?? "");
    setConfig(item.config);
    setEditInit(true);

    // Load user meta
    loadUserMeta(numId, umLimit, umOffset);
  }

  async function loadUserMeta(sid: number, lim: number, off: number) {
    setUserMetaLoading(true);
    try {
      const data = await apiJson<PageResponse<UserMeta>>(
        `/api/user-meta?source_meta_id=${sid}&limit=${lim}&offset=${off}`,
      );
      setUserMetaItems(data.items);
      setUserMetaTotal(data.total);
    } catch {
      setUserMetaItems([]);
    } finally {
      setUserMetaLoading(false);
    }
  }

  async function handleSave() {
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await patchMut.mutateAsync({
        entrypoint,
        runtime_pool: runtimePool,
        sig_uri: sigUri || undefined,
        config,
      } as Partial<SourceMeta>);
      setSaveSuccess(true);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function handleRetire() {
    try {
      await retireMut.mutateAsync();
      setRetireDialog(false);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Retire failed");
    }
  }

  async function handleVerify() {
    setVerifyResult(null);
    try {
      const result = await verifyMut.mutateAsync();
      setVerifyResult({ ok: result.ok, message: result.message });
    } catch (e: unknown) {
      setVerifyResult({ ok: false, message: e instanceof Error ? e.message : "Verification failed" });
    }
  }

  async function handleDelete() {
    try {
      await deleteMut.mutateAsync();
      navigate(basePath, { replace: true });
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Delete failed");
      setDeleteDialog(false);
    }
  }

  if (isLoading) return <p className="p-4 text-sm text-gray-500">Loading...</p>;
  if (isError || !item)
    return <p className="p-4 text-sm text-red-500">Failed to load resource.</p>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={() => navigate(basePath)}
          className="text-sm text-blue-600 hover:underline"
        >
          {kind === "agent" ? "Agents" : "MCP Servers"}
        </button>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{item.name}</h1>
        {item.retired && (
          <span className="bg-red-100 text-red-800 text-xs font-medium px-2 py-0.5 rounded">
            Retired
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Detail card */}
        <div className="lg:col-span-2 bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Details
          </h2>

          {/* Readonly fields */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            {[
              ["ID", String(item.id)],
              ["Kind", item.kind],
              ["Name", item.name],
              ["Version", item.version],
              ["Bundle URI", item.bundle_uri ?? "-"],
              [
                "Checksum",
                item.checksum
                  ? item.checksum.replace("sha256:", "").slice(0, 16) + "..."
                  : "-",
              ],
              ["Created", formatDate(item.created_at)],
              ["Updated", formatDate(item.updated_at)],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-xs text-gray-500">{label}</p>
                <p className="text-sm text-gray-900 font-mono break-all">
                  {value}
                </p>
              </div>
            ))}
          </div>

          {/* Editable fields */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Entrypoint
              </label>
              <input
                value={entrypoint}
                onChange={(e) => setEntrypoint(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Runtime Pool
              </label>
              <select
                value={runtimePool}
                onChange={(e) => setRuntimePool(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {runtimeKinds.map((rk) => (
                  <option key={rk} value={rk}>
                    {rk}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Signature URI
              </label>
              <input
                value={sigUri}
                onChange={(e) => setSigUri(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="s3://bucket/path/bundle.sig"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Config (JSON)
              </label>
              <p className="text-xs text-amber-600 mb-1">
                Note: Changing config is allowed, but warm pods will not reload
                automatically. Consider creating a new version for semantic
                changes.
              </p>
              <JsonEditor value={config} onChange={setConfig} />
            </div>

            {saveError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                {saveError}
              </p>
            )}
            {saveSuccess && (
              <p className="text-sm text-green-600 bg-green-50 border border-green-200 rounded px-3 py-2">
                Saved successfully.
              </p>
            )}

            <button
              onClick={handleSave}
              disabled={patchMut.isPending}
              className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {patchMut.isPending ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>

        {/* Actions panel */}
        <div className="bg-white shadow rounded-lg p-6 h-fit">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Actions
          </h2>
          <div className="space-y-3">
            {item.bundle_uri && (
              <button
                onClick={handleVerify}
                disabled={verifyMut.isPending}
                className="w-full text-left px-4 py-2 border border-blue-300 text-blue-700 rounded hover:bg-blue-50 text-sm disabled:opacity-50"
              >
                {verifyMut.isPending ? "Verifying..." : "Verify Integrity"}
              </button>
            )}
            {verifyResult && (
              <p
                className={`text-xs px-3 py-2 rounded ${
                  verifyResult.ok
                    ? "bg-green-50 text-green-700 border border-green-200"
                    : "bg-red-50 text-red-700 border border-red-200"
                }`}
              >
                {verifyResult.message}
              </p>
            )}
            <button
              onClick={() => setSigDialog(true)}
              className="w-full text-left px-4 py-2 border border-gray-300 rounded hover:bg-gray-50 text-sm"
            >
              Upload Signature
            </button>
            {!item.retired && (
              <button
                onClick={() => setRetireDialog(true)}
                className="w-full text-left px-4 py-2 border border-amber-300 text-amber-700 rounded hover:bg-amber-50 text-sm"
              >
                Retire
              </button>
            )}
            <button
              onClick={() => setDeleteDialog(true)}
              className="w-full text-left px-4 py-2 border border-red-300 text-red-700 rounded hover:bg-red-50 text-sm"
            >
              Delete
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="flex gap-4 border-b border-gray-200 px-6">
          {(["user-meta", "access"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === t
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t === "user-meta" ? "User Meta" : "Access"}
            </button>
          ))}
        </div>

        <div className="p-6">
          {activeTab === "user-meta" && (
            <div>
              {userMetaLoading && (
                <p className="text-sm text-gray-500">Loading...</p>
              )}
              {!userMetaLoading && (
                <>
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead>
                      <tr>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Principal ID
                        </th>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Config Keys
                        </th>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Secrets Ref
                        </th>
                        <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                          Updated
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {userMetaItems.length === 0 && (
                        <tr>
                          <td
                            colSpan={4}
                            className="px-4 py-6 text-sm text-gray-500 text-center"
                          >
                            No user meta entries.
                          </td>
                        </tr>
                      )}
                      {userMetaItems.map((um) => (
                        <tr
                          key={um.principal_id}
                          onClick={() =>
                            navigate(
                              `${basePath}/${numId}/user-meta/${encodeURIComponent(um.principal_id)}`,
                            )
                          }
                          className="hover:bg-gray-50 cursor-pointer"
                        >
                          <td className="px-4 py-3 text-sm text-gray-900">
                            {um.principal_id}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600">
                            {Object.keys(um.config ?? {}).length} keys
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600 font-mono">
                            {um.secrets_ref ?? "-"}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-500">
                            {formatDate(um.updated_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Paginator
                    total={userMetaTotal}
                    limit={umLimit}
                    offset={umOffset}
                    onOffsetChange={(o) => {
                      setUmOffset(o);
                      loadUserMeta(numId, umLimit, o);
                    }}
                  />
                </>
              )}
            </div>
          )}

          {activeTab === "access" && (
            <AccessList
              sourceMetaId={numId}
              kind={item.kind}
              name={item.name}
            />
          )}
        </div>
      </div>

      {/* Dialogs */}
      <ConfirmDialog
        open={retireDialog}
        title="Retire resource"
        description={`Are you sure you want to retire "${item.name}"? It will no longer be available to new invocations.`}
        confirmLabel="Retire"
        destructive
        onConfirm={handleRetire}
        onCancel={() => setRetireDialog(false)}
      />
      <ConfirmDialog
        open={deleteDialog}
        title="Delete resource"
        description={`Permanently delete "${item.name}" version ${item.version}? This action cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteDialog(false)}
      />
      <SignatureUploadDialog
        open={sigDialog}
        sourceMetaId={numId}
        onClose={() => setSigDialog(false)}
        onSuccess={() => setSigDialog(false)}
      />
    </div>
  );
}
