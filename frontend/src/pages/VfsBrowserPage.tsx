import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { VfsBreadcrumbs } from "../components/VfsBreadcrumbs";
import {
  useCreateVfsFile,
  useCreateVfsFolder,
  useDeleteVfsPath,
  usePatchVfsFile,
  useVfsEntries,
  useVfsFile,
  vfsErrorMessage,
  type VfsEntry,
} from "../hooks/useVfs";
import { formatVfsSize, joinVfsPath, normalizeVfsDir } from "../lib/vfsPaths";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function VfsBrowserPage() {
  const { kind = "agent", name = "" } = useParams<{ kind: string; name: string }>();
  const navigate = useNavigate();
  const decodedName = decodeURIComponent(name);

  const [dirPath, setDirPath] = useState("/");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [showNewFileModal, setShowNewFileModal] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [newFileName, setNewFileName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<VfsEntry | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError } = useVfsEntries(kind, decodedName, dirPath);
  const { data: fileData, isLoading: fileLoading } = useVfsFile(
    kind,
    decodedName,
    selectedPath,
  );
  const createFile = useCreateVfsFile(kind, decodedName);
  const patchFile = usePatchVfsFile(kind, decodedName);
  const deletePath = useDeleteVfsPath(kind, decodedName);
  const createFolder = useCreateVfsFolder(kind, decodedName);

  const items = data?.items ?? [];

  useEffect(() => {
    if (fileData && !editorDirty) {
      setEditorContent(fileData.content);
    }
  }, [fileData, editorDirty]);

  function openDir(entry: VfsEntry) {
    if (!entry.is_dir) return;
    const next = entry.path.endsWith("/") ? entry.path : `${entry.path}/`;
    setDirPath(normalizeVfsDir(next));
    setSelectedPath(null);
    setEditorDirty(false);
    setActionError(null);
  }

  function openFile(entry: VfsEntry) {
    if (entry.is_dir) return;
    setSelectedPath(entry.path);
    setEditorDirty(false);
    setActionError(null);
  }

  async function handleSave() {
    if (!selectedPath) return;
    setActionError(null);
    try {
      await patchFile.mutateAsync({ path: selectedPath, content: editorContent });
      setEditorDirty(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleCreateFolder(e: React.FormEvent) {
    e.preventDefault();
    setActionError(null);
    try {
      await createFolder.mutateAsync({
        parent_path: dirPath,
        name: folderName.trim(),
      });
      setFolderName("");
      setShowFolderModal(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleCreateFile(e: React.FormEvent) {
    e.preventDefault();
    const fileName = newFileName.trim();
    if (!fileName) return;
    const path = joinVfsPath(dirPath === "/" ? "/" : dirPath.replace(/\/$/, ""), fileName);
    setActionError(null);
    try {
      const created = await createFile.mutateAsync({ path, content: "" });
      setNewFileName("");
      setShowNewFileModal(false);
      setSelectedPath(created.path);
      setEditorContent("");
      setEditorDirty(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length) return;
    setActionError(null);
    try {
      for (const file of Array.from(files)) {
        const text = await file.text();
        const path = joinVfsPath(dirPath === "/" ? "/" : dirPath.replace(/\/$/, ""), file.name);
        await createFile.mutateAsync({ path, content: text });
      }
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    } finally {
      e.target.value = "";
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await deletePath.mutateAsync(deleteTarget.path);
      if (selectedPath === deleteTarget.path) {
        setSelectedPath(null);
        setEditorContent("");
      }
      setDeleteTarget(null);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
      setDeleteTarget(null);
    }
  }

  function handleDownload(entry: VfsEntry) {
    if (entry.is_dir) return;
    const blob = new Blob([editorContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = entry.name;
    a.click();
    URL.revokeObjectURL(url);
  }

  const editorTitle = useMemo(() => {
    if (!selectedPath) return null;
    return selectedPath.split("/").filter(Boolean).pop() ?? selectedPath;
  }, [selectedPath]);

  return (
    <div className="flex flex-col min-h-[calc(100dvh-10rem)]">
      <div className="flex flex-wrap items-center gap-2 mb-2 text-sm shrink-0">
        <button
          type="button"
          onClick={() => navigate("/vfs")}
          className="text-blue-600 hover:underline"
        >
          VFS
        </button>
        <span className="text-gray-400">/</span>
        <span className="font-medium text-gray-900">{decodedName}</span>
      </div>

      <div className="shrink-0">
      <PageHeader title={`${decodedName} — /agent/`}>
        <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
          Shared VFS
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
          onClick={() => setShowNewFileModal(true)}
          className="bg-white border border-gray-300 text-gray-700 px-3 py-2 rounded text-sm hover:bg-gray-50"
        >
          New File
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="bg-blue-600 text-white px-3 py-2 rounded text-sm hover:bg-blue-700"
        >
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.md,.json,.yaml,.yml,.csv,.ts,.tsx,.js,.py"
          className="hidden"
          onChange={handleUpload}
        />
        <Link
          to={`/agents`}
          className="text-sm text-gray-600 hover:text-blue-600 underline"
        >
          Agent settings
        </Link>
      </PageHeader>
      </div>

      <div className="shrink-0">
      <VfsBreadcrumbs
        path={dirPath}
        onNavigate={(path) => {
          setDirPath(path);
          setSelectedPath(null);
          setEditorDirty(false);
        }}
      />
      </div>

      {actionError && (
        <div className="mb-4 shrink-0 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
        <div className="bg-white shadow rounded-lg overflow-hidden flex flex-col min-h-[40vh] lg:min-h-0">
          <div className="overflow-auto flex-1 min-h-0">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Size</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Modified</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                    Loading…
                  </td>
                </tr>
              )}
              {isError && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-red-600">
                    Failed to load entries
                  </td>
                </tr>
              )}
              {!isLoading && !isError && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                    Empty folder — create a file to seed the agent knowledge base.
                  </td>
                </tr>
              )}
              {items.map((item) => (
                <tr
                  key={item.path}
                  className={selectedPath === item.path ? "bg-blue-50" : undefined}
                >
                  <td className="px-4 py-3 text-sm">
                    {item.is_dir ? (
                      <button
                        type="button"
                        className="font-medium text-blue-700 hover:underline"
                        onClick={() => openDir(item)}
                      >
                        {item.name}/
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="text-gray-900 hover:text-blue-700"
                        onClick={() => openFile(item)}
                      >
                        {item.name}
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {item.is_dir ? "folder" : "file"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatVfsSize(item.size)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatDate(item.modified_at)}</td>
                  <td className="px-4 py-3 text-right text-sm space-x-2">
                    {!item.is_dir && selectedPath === item.path && (
                      <button
                        type="button"
                        className="text-blue-600 hover:underline"
                        onClick={() => handleDownload(item)}
                      >
                        Download
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-red-600 hover:underline"
                      onClick={() => setDeleteTarget(item)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>

        <div className="bg-white shadow rounded-lg p-4 flex flex-col min-h-[40vh] lg:min-h-0">
          {!selectedPath && (
            <p className="text-sm text-gray-500">Select a file to view or edit.</p>
          )}
          {selectedPath && (
            <>
              <div className="flex items-center justify-between mb-3 gap-2 shrink-0">
                <h2 className="text-sm font-semibold text-gray-900 truncate">{editorTitle}</h2>
                <button
                  type="button"
                  disabled={!editorDirty || patchFile.isPending}
                  onClick={handleSave}
                  className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {patchFile.isPending ? "Saving…" : "Save"}
                </button>
              </div>
              {fileLoading ? (
                <p className="text-sm text-gray-500">Loading file…</p>
              ) : (
                <textarea
                  value={editorContent}
                  onChange={(e) => {
                    setEditorContent(e.target.value);
                    setEditorDirty(true);
                  }}
                  className="flex-1 min-h-0 w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  spellCheck={false}
                />
              )}
            </>
          )}
        </div>
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

      {showNewFileModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowNewFileModal(false)} />
          <form
            onSubmit={handleCreateFile}
            className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl mx-4"
          >
            <h2 className="text-lg font-semibold mb-4">New File</h2>
            <input
              value={newFileName}
              onChange={(e) => setNewFileName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-4"
              placeholder="notes.md"
              required
            />
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setShowNewFileModal(false)} className="px-4 py-2 text-sm border rounded">
                Cancel
              </button>
              <button type="submit" className="px-4 py-2 text-sm rounded bg-blue-600 text-white">
                Create
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete selected path?"
        description={
          deleteTarget?.is_dir
            ? "This deletes the folder and all files under it."
            : "This file will be permanently removed from the agent VFS."
        }
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
