import { useState } from "react";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  useCreateMyApiKey,
  useDisableMyApiKey,
  useMyApiKeys,
  type ApiKeyListItem,
} from "../hooks/useMyApiKeys";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function KeyStatusBadge({ item }: { item: ApiKeyListItem }) {
  if (item.disabled) {
    return (
      <span className="text-xs font-medium px-2 py-0.5 rounded bg-gray-100 text-gray-600">
        Revoked
      </span>
    );
  }
  if (item.expires_at && new Date(item.expires_at) < new Date()) {
    return (
      <span className="text-xs font-medium px-2 py-0.5 rounded bg-amber-100 text-amber-800">
        Expired
      </span>
    );
  }
  return (
    <span className="text-xs font-medium px-2 py-0.5 rounded bg-green-100 text-green-800">
      Active
    </span>
  );
}

export function MyApiKeysPanel() {
  const { data, isLoading, isError } = useMyApiKeys();
  const createMut = useCreateMyApiKey();
  const disableMut = useDisableMyApiKey();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [createdKeyName, setCreatedKeyName] = useState("");

  const [revokeTarget, setRevokeTarget] = useState<ApiKeyListItem | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const items = data?.items ?? [];

  function resetCreateForm() {
    setName("");
    setExpiresInDays("");
    setCreateError(null);
  }

  function openCreateDialog() {
    resetCreateForm();
    setCreateOpen(true);
  }

  function closeCreateDialog() {
    setCreateOpen(false);
    resetCreateForm();
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);

    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError("Name is required");
      return;
    }

    let expires: number | null = null;
    if (expiresInDays.trim()) {
      const parsed = Number(expiresInDays);
      if (!Number.isInteger(parsed) || parsed < 1 || parsed > 3650) {
        setCreateError("Expires in days must be between 1 and 3650");
        return;
      }
      expires = parsed;
    }

    try {
      const created = await createMut.mutateAsync({
        name: trimmed,
        expires_in_days: expires,
      });
      closeCreateDialog();
      setCreatedKeyName(created.name);
      setCreatedKey(created.key);
      setCopied(false);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create API key");
    }
  }

  async function handleRevoke() {
    if (!revokeTarget) return;
    setRevokeError(null);
    try {
      await disableMut.mutateAsync(revokeTarget.id);
      setRevokeTarget(null);
    } catch (err: unknown) {
      setRevokeError(err instanceof Error ? err.message : "Failed to revoke API key");
    }
  }

  async function handleCopy() {
    if (!createdKey) return;
    try {
      await navigator.clipboard.writeText(createdKey);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
        <div>
          <h2 className="text-base font-semibold text-gray-900">API Keys</h2>
          <p className="text-sm text-gray-500 mt-1">
            Long-lived tokens for programmatic access (e.g.{" "}
            <code className="text-xs bg-gray-100 px-1 rounded">/v1/agents/invoke</code>
            ). Grant agent/MCP access separately under Users or resource Access tabs.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateDialog}
          className="shrink-0 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium"
        >
          Create API key
        </button>
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {isError && (
        <p className="text-sm text-red-600">Failed to load API keys.</p>
      )}
      {revokeError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {revokeError}
        </p>
      )}

      {!isLoading && !isError && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead>
              <tr>
                <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Name
                </th>
                <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Created
                </th>
                <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Expires
                </th>
                <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="bg-gray-50 px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-sm text-gray-500 text-center">
                    No API keys yet.
                  </td>
                </tr>
              )}
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    {item.name}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatDate(item.created_at)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {formatDate(item.expires_at)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <KeyStatusBadge item={item} />
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {!item.disabled && (
                      <button
                        type="button"
                        onClick={() => setRevokeTarget(item)}
                        className="text-red-600 hover:underline text-sm"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={closeCreateDialog} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 z-10">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Create API key</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label
                  htmlFor="api-key-name"
                  className="block text-sm font-medium text-gray-700 mb-1"
                >
                  Name
                </label>
                <input
                  id="api-key-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={128}
                  placeholder="path-graph-pipeline"
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label
                  htmlFor="api-key-expires"
                  className="block text-sm font-medium text-gray-700 mb-1"
                >
                  Expires in days (optional)
                </label>
                <input
                  id="api-key-expires"
                  type="number"
                  min={1}
                  max={3650}
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(e.target.value)}
                  placeholder="365"
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-400 mt-1">Leave empty for no expiration.</p>
              </div>
              {createError && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                  {createError}
                </p>
              )}
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeCreateDialog}
                  className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMut.isPending}
                  className="px-4 py-2 rounded bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {createMut.isPending ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {createdKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-lg w-full mx-4 z-10">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">API key created</h3>
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-4">
              Copy this key now. You will not be able to see it again.
            </p>
            <p className="text-xs text-gray-500 mb-1">{createdKeyName}</p>
            <div className="flex gap-2 items-stretch">
              <code className="flex-1 text-sm bg-gray-100 border border-gray-200 rounded px-3 py-2 break-all">
                {createdKey}
              </code>
              <button
                type="button"
                onClick={handleCopy}
                className="shrink-0 px-3 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="flex justify-end mt-6">
              <button
                type="button"
                onClick={() => {
                  setCreatedKey(null);
                  setCreatedKeyName("");
                  setCopied(false);
                }}
                className="px-4 py-2 rounded bg-blue-600 text-white text-sm hover:bg-blue-700"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke API key"
        description={
          revokeTarget
            ? `Revoke "${revokeTarget.name}"? Programs using this key will stop working immediately.`
            : ""
        }
        confirmLabel="Revoke"
        destructive
        onConfirm={handleRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
