import { useMemo, useRef, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import {
  bucketErrorMessage,
  formatBucketSize,
  prefixSegments,
  useBucketDownloadUrl,
  useBucketInfo,
  useBucketObjects,
  useCreateBucketFolder,
  useDeleteBucketObjects,
  useMoveBucketObjects,
  useUploadBucketObject,
  type BucketObjectItem,
} from "../hooks/useBucket";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

interface Props {
  embedded?: boolean;
}

export function BucketPage({ embedded = false }: Props) {
  const [prefix, setPrefix] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [folderName, setFolderName] = useState("");
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [showMoveModal, setShowMoveModal] = useState(false);
  const [moveDest, setMoveDest] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: info } = useBucketInfo();
  const { data, isLoading, isError } = useBucketObjects(prefix);
  const createFolder = useCreateBucketFolder();
  const uploadObject = useUploadBucketObject();
  const deleteObjects = useDeleteBucketObjects();
  const moveObjects = useMoveBucketObjects();
  const downloadUrl = useBucketDownloadUrl();

  const breadcrumbs = useMemo(() => prefixSegments(prefix), [prefix]);
  const items = data?.items ?? [];

  const selectableKeys = items.filter((item) => !item.in_use).map((item) => item.key);
  const allSelected =
    selectableKeys.length > 0 && selectableKeys.every((key) => selected.has(key));

  function toggleSelect(key: string, inUse: boolean) {
    if (inUse) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectableKeys));
    }
  }

  function openFolder(item: BucketObjectItem) {
    if (item.kind !== "folder") return;
    setPrefix(item.key);
    setSelected(new Set());
    setActionError(null);
  }

  async function handleCreateFolder(e: React.FormEvent) {
    e.preventDefault();
    setActionError(null);
    try {
      await createFolder.mutateAsync({ parent_prefix: prefix, name: folderName.trim() });
      setFolderName("");
      setShowFolderModal(false);
    } catch (err) {
      setActionError(bucketErrorMessage(err));
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length) return;
    setActionError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadObject.mutateAsync({ parent_prefix: prefix, file });
      }
    } catch (err) {
      setActionError(bucketErrorMessage(err));
    } finally {
      e.target.value = "";
    }
  }

  async function handleDelete() {
    setActionError(null);
    try {
      await deleteObjects.mutateAsync([...selected]);
      setSelected(new Set());
      setShowDeleteConfirm(false);
    } catch (err) {
      setActionError(bucketErrorMessage(err));
      setShowDeleteConfirm(false);
    }
  }

  async function handleMove(e: React.FormEvent) {
    e.preventDefault();
    setActionError(null);
    try {
      await moveObjects.mutateAsync({ sources: [...selected], dest_prefix: moveDest.trim() });
      setSelected(new Set());
      setMoveDest("");
      setShowMoveModal(false);
    } catch (err) {
      setActionError(bucketErrorMessage(err));
    }
  }

  async function handleDownload(item: BucketObjectItem) {
    if (item.kind !== "file") return;
    setActionError(null);
    try {
      const result = await downloadUrl.mutateAsync(item.key);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setActionError(bucketErrorMessage(err));
    }
  }

  const backendBadge =
    info?.backend === "s3"
      ? `S3: ${info.bucket ?? info.root_label}`
      : `Local: ${info?.root_label ?? "…"}`;

  return (
    <div>
      <PageHeader title={embedded ? undefined : "Bucket"}>
        <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
          {backendBadge}
        </span>
        <button
          type="button"
          onClick={() => setShowFolderModal(true)}
          className="bg-white border border-gray-300 text-gray-700 px-3 py-2 rounded text-sm hover:bg-gray-50"
        >
          New Folder
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="bg-blue-600 text-white px-3 py-2 rounded text-sm hover:bg-blue-700"
        >
          Upload
        </button>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleUpload} />
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-gray-600">
        {breadcrumbs.map((crumb, idx) => (
          <span key={crumb.prefix || "root"} className="inline-flex items-center gap-2">
            {idx > 0 && <span>/</span>}
            <button
              type="button"
              className={`hover:text-blue-600 ${crumb.prefix === prefix ? "font-semibold text-gray-900" : ""}`}
              onClick={() => {
                setPrefix(crumb.prefix);
                setSelected(new Set());
              }}
            >
              {crumb.label}
            </button>
          </span>
        ))}
      </div>

      {actionError && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {selected.size > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setShowMoveModal(true)}
            className="bg-white border border-gray-300 px-3 py-2 rounded text-sm hover:bg-gray-50"
          >
            Move ({selected.size})
          </button>
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700"
          >
            Delete ({selected.size})
          </button>
        </div>
      )}

      <div className="bg-white shadow rounded-lg overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  aria-label="Select all"
                />
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Size</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Modified</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {isError && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-red-600">
                  Failed to load objects
                </td>
              </tr>
            )}
            {!isLoading && !isError && items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                  Empty folder
                </td>
              </tr>
            )}
            {items.map((item) => (
              <tr key={item.key} className={item.in_use ? "bg-amber-50/40" : undefined}>
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(item.key)}
                    disabled={item.in_use}
                    title={item.in_use ? "Referenced by Source Meta" : undefined}
                    onChange={() => toggleSelect(item.key, item.in_use)}
                    aria-label={`Select ${item.name}`}
                  />
                </td>
                <td className="px-4 py-3 text-sm">
                  {item.kind === "folder" ? (
                    <button
                      type="button"
                      className="font-medium text-blue-700 hover:underline"
                      onClick={() => openFolder(item)}
                    >
                      {item.name}/
                    </button>
                  ) : (
                    <span className="text-gray-900">{item.name}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 capitalize">{item.kind}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{formatBucketSize(item.size)}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{formatDate(item.last_modified)}</td>
                <td className="px-4 py-3 text-sm">
                  {item.in_use ? (
                    <span className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                      In use
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-3 text-right text-sm">
                  {item.kind === "file" && (
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => handleDownload(item)}
                    >
                      Download
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showFolderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowFolderModal(false)} />
          <form
            onSubmit={handleCreateFolder}
            className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl mx-4"
          >
            <h2 className="text-lg font-semibold mb-4">New Folder</h2>
            <input
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-4"
              placeholder="folder-name"
              required
            />
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setShowFolderModal(false)} className="px-4 py-2 text-sm border rounded">
                Cancel
              </button>
              <button type="submit" className="px-4 py-2 text-sm rounded bg-blue-600 text-white">
                Create
              </button>
            </div>
          </form>
        </div>
      )}

      {showMoveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowMoveModal(false)} />
          <form
            onSubmit={handleMove}
            className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl mx-4"
          >
            <h2 className="text-lg font-semibold mb-2">Move Objects</h2>
            <p className="text-sm text-gray-600 mb-4">
              Destination prefix (folder). For rename of a single file, enter the new key (e.g. `new.zip`).
            </p>
            <input
              value={moveDest}
              onChange={(e) => setMoveDest(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-4"
              placeholder="destination/"
              required
            />
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setShowMoveModal(false)} className="px-4 py-2 text-sm border rounded">
                Cancel
              </button>
              <button type="submit" className="px-4 py-2 text-sm rounded bg-blue-600 text-white">
                Move
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete selected objects?"
        description="This action cannot be undone. Objects referenced by Source Meta are blocked."
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}
