import { Link } from "react-router-dom";
import { ConfirmDialog } from "./ConfirmDialog";
import { PageHeader } from "./PageHeader";
import { VfsBreadcrumbs } from "./VfsBreadcrumbs";
import type { useVfsBrowserController } from "../hooks/useVfsBrowserController";
import { formatVfsSize } from "../lib/vfsPaths";
import type { VfsEntry } from "../hooks/useVfs";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

type Controller = ReturnType<typeof useVfsBrowserController>;

export type VfsBrowserViewProps = {
  backLabel: string;
  onBack: () => void;
  entityName: string;
  mountLabel: string;
  scopeBadge: string;
  settingsLink?: { to: string; label: string };
  emptyFolderMessage: string;
  deleteFileDescription: string;
  deleteFolderDescription: string;
  items: VfsEntry[];
  isLoading: boolean;
  isError: boolean;
  fileLoading: boolean;
  controller: Controller;
};

export function VfsBrowserView({
  backLabel,
  onBack,
  entityName,
  mountLabel,
  scopeBadge,
  settingsLink,
  emptyFolderMessage,
  deleteFileDescription,
  deleteFolderDescription,
  items,
  isLoading,
  isError,
  fileLoading,
  controller,
}: VfsBrowserViewProps) {
  const {
    dirPath,
    setDirPath,
    selectedPath,
    editorContent,
    setEditorContent,
    editorDirty,
    setEditorDirty,
    actionError,
    showFolderModal,
    setShowFolderModal,
    showNewFileModal,
    setShowNewFileModal,
    folderName,
    setFolderName,
    newFileName,
    setNewFileName,
    deleteTarget,
    setDeleteTarget,
    fileInputRef,
    openDir,
    openFile,
    handleSave,
    handleCreateFolder,
    handleCreateFile,
    handleUpload,
    handleDelete,
    handleDownload,
    editorTitle,
    patchFile,
  } = controller;

  return (
    <div className="flex flex-col h-[calc(100dvh-10rem)] max-h-[calc(100dvh-10rem)] min-h-0">
      <div className="flex flex-wrap items-center gap-2 mb-2 text-sm shrink-0">
        <button type="button" onClick={onBack} className="text-blue-600 hover:underline">
          {backLabel}
        </button>
        <span className="text-gray-400">/</span>
        <span className="font-medium text-gray-900">{entityName}</span>
      </div>

      <div className="shrink-0">
        <PageHeader title={`${entityName} — ${mountLabel}`}>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
            {scopeBadge}
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
          {settingsLink && (
            <Link to={settingsLink.to} className="text-sm text-gray-600 hover:text-blue-600 underline">
              {settingsLink.label}
            </Link>
          )}
        </PageHeader>
      </div>

      <div className="shrink-0">
        <VfsBreadcrumbs
          path={dirPath}
          onNavigate={(path) => {
            setDirPath(path);
          }}
        />
      </div>

      {actionError && (
        <div className="mb-4 shrink-0 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0 overflow-hidden">
        <div className="bg-white shadow rounded-lg overflow-hidden flex flex-col min-h-0 h-full max-h-full">
          <div className="overflow-y-auto flex-1 min-h-0 max-h-[45vh] lg:max-h-none">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Name
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Size
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Modified
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Actions
                  </th>
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
                      {emptyFolderMessage}
                    </td>
                  </tr>
                )}
                {items.map((item) => (
                  <tr
                    key={item.path}
                    className={selectedPath === item.path ? "bg-blue-50" : undefined}
                  >
                    <td className="px-4 py-3 text-sm text-left align-top">
                      {item.is_dir ? (
                        <button
                          type="button"
                          className="block w-full text-left break-words font-medium text-blue-700 hover:underline"
                          onClick={() => openDir(item)}
                        >
                          {item.name}/
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="block w-full text-left break-words text-gray-900 hover:text-blue-700"
                          onClick={() => openFile(item)}
                        >
                          {item.name}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 align-top whitespace-nowrap">
                      {item.is_dir ? "folder" : "file"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 align-top whitespace-nowrap">{formatVfsSize(item.size)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 align-top whitespace-nowrap">
                      {formatDate(item.modified_at)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm space-x-2 align-top whitespace-nowrap">
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

        <div className="bg-white shadow rounded-lg p-4 flex flex-col min-h-0 h-full max-h-full overflow-hidden">
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
              <button
                type="button"
                onClick={() => setShowFolderModal(false)}
                className="px-4 py-2 text-sm border rounded"
              >
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
              <button
                type="button"
                onClick={() => setShowNewFileModal(false)}
                className="px-4 py-2 text-sm border rounded"
              >
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
        description={deleteTarget?.is_dir ? deleteFolderDescription : deleteFileDescription}
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
