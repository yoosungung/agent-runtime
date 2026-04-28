import { useState } from "react";
import { useSourceMetaAccess } from "../hooks/useSourceMeta";
import { useUserAccess, useGrantAccess, useRevokeAccess, useBulkRevokeAccess } from "../hooks/useUsers";
import { Paginator } from "./Paginator";
import { UserSearchInput } from "./UserSearchInput";
import { usePagination } from "../hooks/usePagination";
import { apiJson, type PageResponse } from "../lib/api";

interface SourceOption {
  id: number;
  kind: string;
  name: string;
  version: string;
}

interface Props {
  userId?: number;
  sourceMetaId?: number;
  kind?: "agent" | "mcp";
  name?: string;
}

// Resource-view: show users for a given source_meta
function ResourceAccessList({
  sourceMetaId,
  kind,
  name,
}: {
  sourceMetaId: number;
  kind?: string;
  name?: string;
}) {
  const { limit, offset, setOffset } = usePagination(20);
  const { data, isLoading, isError } = useSourceMetaAccess(sourceMetaId, {
    limit,
    offset,
  });
  const [addError, setAddError] = useState<string | null>(null);

  const grantMut = useGrantAccess(0);

  // We need per-user grant/revoke, so we create inline mutations by userId
  // Instead, we'll use a helper that calls the raw API

  async function handleGrant(user: { id: number; username: string }) {
    if (!kind || !name) return;
    setAddError(null);
    try {
      await apiJson(`/api/users/${user.id}/access`, {
        method: "POST",
        body: JSON.stringify({ kind, name }),
      });
      // Invalidate both
      grantMut.reset();
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : "Failed to grant access");
    }
  }

  if (isLoading) return <p className="text-sm text-gray-500">Loading...</p>;
  if (isError) return <p className="text-sm text-red-500">Failed to load access list</p>;

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <UserSearchInput
          onSelect={handleGrant}
          placeholder="Add user by username..."
        />
      </div>
      {addError && <p className="text-sm text-red-600 mb-2">{addError}</p>}
      <table className="min-w-full divide-y divide-gray-200">
        <thead>
          <tr>
            <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Username
            </th>
            <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              User ID
            </th>
            <th className="bg-gray-50 px-4 py-3" />
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {data?.items.length === 0 && (
            <tr>
              <td colSpan={3} className="px-4 py-4 text-sm text-gray-500 text-center">
                No users have access to this resource.
              </td>
            </tr>
          )}
          {data?.items.map((entry) => (
            <tr key={entry.user_id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-sm text-gray-900">
                {entry.username}
              </td>
              <td className="px-4 py-3 text-sm text-gray-500">
                {entry.user_id}
              </td>
              <td className="px-4 py-3 text-right">
                <RevokeButton
                  userId={entry.user_id}
                  kind={kind ?? entry.kind}
                  name={name ?? entry.name}
                  sourceMetaId={sourceMetaId}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && (
        <Paginator
          total={data.total}
          limit={limit}
          offset={offset}
          onOffsetChange={setOffset}
        />
      )}
    </div>
  );
}

function RevokeButton({
  userId,
  kind,
  name,
  sourceMetaId,
}: {
  userId: number;
  kind: string;
  name: string;
  sourceMetaId?: number;
}) {
  const revoke = useRevokeAccess(userId, sourceMetaId);
  return (
    <button
      onClick={() => revoke.mutate({ kind, name, sourceMetaId })}
      disabled={revoke.isPending}
      className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
    >
      Revoke
    </button>
  );
}

// User-view: show resources for a given user
function UserAccessList({ userId }: { userId: number }) {
  const { limit, offset, setOffset } = usePagination(20);
  const { data, isLoading, isError } = useUserAccess(userId, { limit, offset });
  const revoke = useRevokeAccess(userId);
  const bulkRevoke = useBulkRevokeAccess(userId);
  const [sourceOptions, setSourceOptions] = useState<SourceOption[]>([]);
  const [addKind, setAddKind] = useState<"agent" | "mcp">("agent");
  const [addName, setAddName] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const grantMut = useGrantAccess(userId);

  async function loadSources(kind: "agent" | "mcp") {
    try {
      const d = await apiJson<PageResponse<SourceOption>>(
        `/api/source-meta?kind=${kind}&limit=100`,
      );
      setSourceOptions(d.items);
    } catch {
      setSourceOptions([]);
    }
  }

  async function handleGrant() {
    if (!addName) return;
    setAddError(null);
    try {
      await grantMut.mutateAsync({ kind: addKind, name: addName });
      setAddName("");
    } catch (e: unknown) {
      setAddError((e instanceof Error ? e.message : null) ?? "Failed to grant access");
    }
  }

  function toggleSelect(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    if (!data) return;
    const allKeys = data.items.map((e) => `${e.kind}/${e.name}`);
    if (allKeys.every((k) => selected.has(k))) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allKeys));
    }
  }

  async function handleBulkRevoke() {
    if (!data || selected.size === 0) return;
    const items = data.items
      .filter((e) => selected.has(`${e.kind}/${e.name}`))
      .map((e) => ({ kind: e.kind, name: e.name }));
    try {
      await bulkRevoke.mutateAsync(items);
      setSelected(new Set());
    } catch (e: unknown) {
      setAddError((e instanceof Error ? e.message : null) ?? "Bulk revoke failed");
    }
  }

  if (isLoading) return <p className="text-sm text-gray-500">Loading...</p>;
  if (isError) return <p className="text-sm text-red-500">Failed to load access list</p>;

  const allKeys = data?.items.map((e) => `${e.kind}/${e.name}`) ?? [];
  const allSelected = allKeys.length > 0 && allKeys.every((k) => selected.has(k));

  return (
    <div>
      <div className="mb-3 flex gap-2 items-end">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Kind</label>
          <select
            value={addKind}
            onChange={(e) => {
              const k = e.target.value as "agent" | "mcp";
              setAddKind(k);
              loadSources(k);
            }}
            onFocus={() => loadSources(addKind)}
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="agent">agent</option>
            <option value="mcp">mcp</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Resource name</label>
          <select
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            className="border border-gray-300 rounded px-3 py-2 w-full text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select resource...</option>
            {sourceOptions.map((s) => (
              <option key={s.id} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleGrant}
          disabled={!addName || grantMut.isPending}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
        >
          Grant
        </button>
      </div>
      {addError && <p className="text-sm text-red-600 mb-2">{addError}</p>}
      {selected.size > 0 && (
        <div className="mb-2 flex items-center gap-3">
          <button
            onClick={handleBulkRevoke}
            disabled={bulkRevoke.isPending}
            className="bg-red-600 text-white px-4 py-1.5 rounded hover:bg-red-700 disabled:opacity-50 text-sm"
          >
            Revoke selected ({selected.size})
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear selection
          </button>
        </div>
      )}
      <table className="min-w-full divide-y divide-gray-200">
        <thead>
          <tr>
            <th className="bg-gray-50 px-3 py-3 w-8">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="rounded border-gray-300"
                aria-label="Select all"
              />
            </th>
            <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Kind
            </th>
            <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Name
            </th>
            <th className="bg-gray-50 px-4 py-3" />
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {data?.items.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-4 text-sm text-gray-500 text-center">
                No resources granted.
              </td>
            </tr>
          )}
          {data?.items.map((entry) => {
            const key = `${entry.kind}/${entry.name}`;
            return (
              <tr key={key} className="hover:bg-gray-50">
                <td className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(key)}
                    onChange={() => toggleSelect(key)}
                    className="rounded border-gray-300"
                    aria-label={`Select ${entry.kind}/${entry.name}`}
                  />
                </td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={`text-xs font-medium px-2 py-0.5 rounded ${
                      entry.kind === "agent"
                        ? "bg-green-100 text-green-800"
                        : "bg-blue-100 text-blue-800"
                    }`}
                  >
                    {entry.kind}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-900">{entry.name}</td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() =>
                      revoke.mutate({ kind: entry.kind, name: entry.name })
                    }
                    disabled={revoke.isPending}
                    className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {data && (
        <Paginator
          total={data.total}
          limit={limit}
          offset={offset}
          onOffsetChange={setOffset}
        />
      )}
    </div>
  );
}

export function AccessList({ userId, sourceMetaId, kind, name }: Props) {
  if (sourceMetaId !== undefined) {
    return (
      <ResourceAccessList
        sourceMetaId={sourceMetaId}
        kind={kind}
        name={name}
      />
    );
  }
  if (userId !== undefined) {
    return <UserAccessList userId={userId} />;
  }
  return null;
}
